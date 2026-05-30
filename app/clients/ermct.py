"""국립중앙의료원 전국 응급의료기관 OpenAPI 클라이언트."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

BASE_URL = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
TRAUMA_CENTER_CODES = {"G001", "G002", "G006"}


@dataclass
class HospitalListItem:
    hpid: str
    hospital_name: str
    address: str
    latitude: float
    longitude: float
    emergency_class: str = ""
    emergency_class_name: str = ""
    duty_tel3: str = ""


@dataclass
class HospitalBedItem:
    hpid: str
    available_er_beds: int = 0
    stroke_center: bool = False
    cardiac_center: bool = False
    ct_available: bool = False
    mri_available: bool = False
    raw: dict[str, str] = field(default_factory=dict)


class ErmctApiError(Exception):
    pass


class ErmctClient:
    def __init__(
        self,
        service_key: str,
        request_delay_sec: float = 0.05,
        timeout_sec: int = 30,
    ):
        self.service_key = unquote(service_key)
        self.request_delay_sec = request_delay_sec
        self.timeout_sec = timeout_sec

    def _get_xml(self, path: str, **params: str | int) -> ET.Element:
        query = {"serviceKey": self.service_key, **params}
        url = f"{BASE_URL}/{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/xml"})

        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:
            raise ErmctApiError(f"API request failed: {path}") from exc
        finally:
            if self.request_delay_sec > 0:
                time.sleep(self.request_delay_sec)

        root = ET.fromstring(body)
        header = _find_child(root, "header")
        if header is not None:
            result_code = _element_text(header, "resultCode")
            if result_code != "00":
                result_msg = _element_text(header, "resultMsg") or _element_text(
                    header, "resultMag"
                )
                raise ErmctApiError(f"{path} failed: {result_code} {result_msg}")
        return root

    def fetch_hospital_list(
        self,
        stage1: str,
        stage2: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[list[HospitalListItem], int]:
        root = self._get_xml(
            "getEgytListInfoInqire",
            Q0=stage1,
            Q1=stage2,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        body = _find_child(root, "body")
        if body is None:
            return [], 0

        total_count = int(_element_text(body, "totalCount", "0") or "0")
        items_el = _find_child(body, "items")
        if items_el is None:
            return [], total_count

        items: list[HospitalListItem] = []
        for item_el in items_el:
            if _local_name(item_el.tag) != "item":
                continue
            lat = _element_text(item_el, "wgs84Lat")
            lon = _element_text(item_el, "wgs84Lon")
            if not lat or not lon:
                continue
            items.append(
                HospitalListItem(
                    hpid=_element_text(item_el, "hpid"),
                    hospital_name=_element_text(item_el, "dutyName"),
                    address=_element_text(item_el, "dutyAddr"),
                    latitude=float(lat),
                    longitude=float(lon),
                    emergency_class=_element_text(item_el, "dutyEmcls"),
                    emergency_class_name=_element_text(item_el, "dutyEmclsName"),
                    duty_tel3=_element_text(item_el, "dutyTel3"),
                )
            )
        return items, total_count

    def fetch_all_hospital_list(self, stage1: str, stage2: str) -> list[HospitalListItem]:
        items: list[HospitalListItem] = []
        page_no = 1
        num_of_rows = 100
        while True:
            page_items, total_count = self.fetch_hospital_list(
                stage1, stage2, page_no=page_no, num_of_rows=num_of_rows
            )
            items.extend(page_items)
            if not page_items or len(items) >= total_count:
                break
            page_no += 1
        return items

    def fetch_bed_info(
        self,
        stage1: str,
        stage2: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> tuple[list[HospitalBedItem], int]:
        root = self._get_xml(
            "getEmrrmRltmUsefulSckbdInfoInqire",
            STAGE1=stage1,
            STAGE2=stage2,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        body = _find_child(root, "body")
        if body is None:
            return [], 0

        total_count = int(_element_text(body, "totalCount", "0") or "0")
        items_el = _find_child(body, "items")
        if items_el is None:
            return [], total_count

        items: list[HospitalBedItem] = []
        for item_el in items_el:
            if _local_name(item_el.tag) != "item":
                continue
            raw = {
                _local_name(child.tag): (child.text or "").strip()
                for child in item_el
            }
            hvec = _parse_int(raw.get("hvec", "0"))
            items.append(
                HospitalBedItem(
                    hpid=raw.get("hpid", ""),
                    available_er_beds=hvec,
                    stroke_center=raw.get("hvcrrtayn", "").upper() == "Y",
                    cardiac_center=raw.get("hvecmoayn", "").upper() == "Y",
                    ct_available=raw.get("hvctayn", "").upper() == "Y",
                    mri_available=raw.get("hvmriayn", "").upper() == "Y",
                    raw=raw,
                )
            )
        return items, total_count

    def fetch_all_bed_info(self, stage1: str, stage2: str) -> list[HospitalBedItem]:
        items: list[HospitalBedItem] = []
        page_no = 1
        num_of_rows = 100
        while True:
            page_items, total_count = self.fetch_bed_info(
                stage1, stage2, page_no=page_no, num_of_rows=num_of_rows
            )
            items.extend(page_items)
            if not page_items or len(items) >= total_count:
                break
            page_no += 1
        return items


def is_trauma_center(emergency_class: str) -> bool:
    return emergency_class in TRAUMA_CENTER_CODES


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _element_text(parent: ET.Element, name: str, default: str = "") -> str:
    child = _find_child(parent, name)
    return (child.text or default).strip() if child is not None else default


def _parse_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
