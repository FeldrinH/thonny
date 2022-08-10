import os.path
import sys
import threading
import urllib.request
from dataclasses import dataclass
from logging import getLogger
from tkinter import ttk
from typing import Any, Dict, List, Optional, Set

from thonny.languages import tr
from thonny.misc_utils import get_win_volume_name, list_volumes
from thonny.ui_utils import MappingCombobox, create_url_label, set_text_if_different, AdvancedLabel
from thonny.workdlg import WorkDialog

logger = getLogger(__name__)

FAKE_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"


@dataclass
class TargetInfo:
    title: str


@dataclass()
class Uf2TargetInfo(TargetInfo):
    path: str
    family: Optional[str]
    model: Optional[str]
    board_id: Optional[str]


class BaseFlasher(WorkDialog):
    def __init__(self, master, autostart=False):
        self._downloaded_variants: List[Dict[str, Any]] = []

        self._last_handled_target = None
        self._last_handled_variant = None

        threading.Thread(target=self._download_variants, daemon=True).start()

        super().__init__(master, autostart)

    def populate_main_frame(self):
        epadx = self.get_large_padding()
        ipadx = self.get_small_padding()
        epady = epadx
        ipady = ipadx

        target_label = ttk.Label(self.main_frame, text="Target volume")
        target_label.grid(row=1, column=1, sticky="e", padx=(epadx, 0), pady=(epady, 0))
        self._target_combo = MappingCombobox(self.main_frame, exportselection=False)
        self._target_combo.grid(
            row=1, column=2, sticky="nsew", padx=(ipadx, epadx), pady=(epady, 0)
        )

        self._target_info_label = ttk.Label(self.main_frame, text="model")
        self._target_info_label.grid(row=2, column=1, sticky="e", padx=(epadx, 0), pady=(ipady, 0))
        self._target_info_content_label = ttk.Label(self.main_frame)
        self._target_info_content_label.grid(
            row=2, column=2, sticky="w", padx=(ipadx, epadx), pady=(ipady, 0)
        )

        variant_label = ttk.Label(self.main_frame, text="MicroPython variant")
        variant_label.grid(row=5, column=1, sticky="e", padx=(epadx, 0), pady=(epady, 0))
        self._variant_combo = MappingCombobox(self.main_frame, exportselection=False)
        self._variant_combo.grid(
            row=5, column=2, sticky="nsew", padx=(ipadx, epadx), pady=(epady, 0)
        )

        version_label = ttk.Label(self.main_frame, text="version")
        version_label.grid(row=6, column=1, sticky="e", padx=(epadx, 0), pady=(ipady, 0))
        self._version_combo = MappingCombobox(self.main_frame, exportselection=False)
        self._version_combo.grid(
            row=6, column=2, sticky="nsew", padx=(ipadx, epadx), pady=(ipady, 0)
        )

        variant_info_label = ttk.Label(self.main_frame, text="info")
        variant_info_label.grid(row=7, column=1, sticky="e", padx=(epadx, 0), pady=(ipady, 0))
        self._variant_info_content_label = AdvancedLabel(self.main_frame)
        self._variant_info_content_label.grid(
            row=7, column=2, sticky="w", padx=(ipadx, epadx), pady=(ipady, 0)
        )

        self.main_frame.columnconfigure(2, weight=1)

    def update_ui(self):
        if self._state == "idle":
            targets = self.find_targets()
            if targets != self._target_combo.mapping:
                self.show_new_targets(targets)
                self._last_handled_target = None

            current_target = self._target_combo.get_selected_value()
            if not current_target:
                self._variant_combo.set_mapping({})
                self._variant_combo.select_none()
            elif current_target != self._last_handled_target and self._downloaded_variants:
                self._handle_new_target(current_target)
                self._last_handled_target = current_target
                self._last_handled_variant = None
            self._update_target_info()

            current_variant = self._variant_combo.get_selected_value()
            if not current_variant:
                self._version_combo.select_none()
                self._version_combo.set_mapping({})
            elif current_variant != self._last_handled_variant:
                self._handle_new_variant(current_variant)
                self._last_handled_variant = current_variant
            self._update_variant_info()

        super().update_ui()

    def _get_variants_url(self) -> str:
        return "https://raw.githubusercontent.com/thonny/thonny/master/data/micropython-variants-uf2.json"

    def find_targets(self) -> Dict[str, TargetInfo]:
        paths = [
            vol
            for vol in list_volumes(skip_letters=["A"])
            if os.path.isfile(os.path.join(vol, "INFO_UF2.TXT"))
        ]

        result = {}
        for path in paths:
            try:
                target_info = self._create_target_info(path)
                result[target_info.title] = target_info
            except:
                # the disk may have been ejected during read or smth like this
                logger.exception("Could not create target info")

        return result

    def show_new_targets(self, targets: Dict[str, TargetInfo]) -> None:
        self._target_combo.set_mapping(targets)
        if len(targets) == 1:
            self._target_combo.select_value(list(targets.values())[0])
        else:
            self._target_combo.select_none()

    def _update_target_info(self):
        current_target = self._target_combo.get_selected_value()
        if current_target is not None:
            if current_target.model:
                if current_target.model == "Raspberry Pi RP2":
                    # too general to be called model
                    text = "RP2"
                    label = "family"
                else:
                    text = current_target.model
                    label = "model"
            elif current_target.board_id:
                text = current_target.board_id
                label = "board id"
            elif current_target.family:
                text = current_target.family
                label = "family"
            else:
                text = "Unknown board"
                label = "info"

        elif not self._target_combo.mapping:
            text = "[no suitable targets detected]"
            label = ""
        else:
            text = f"[found {len(self._target_combo.mapping)} targets, please select one]"
            label = ""

        set_text_if_different(self._target_info_content_label, text)
        set_text_if_different(self._target_info_label, label)

    def _update_variant_info(self):
        current_variant = self._variant_combo.get_selected_value()
        if not self._downloaded_variants:
            url = None
            text = "[downloading variants info ...]"
        elif current_variant:
            url = current_variant["info_url"]
            text = url
        elif self._variant_combo.mapping:
            url = None
            text = f"[select one from {len(self._variant_combo.mapping)} variants]"
        else:
            url = None
            text = ""

        set_text_if_different(self._variant_info_content_label, text)
        self._variant_info_content_label.set_url(url)

    def _handle_new_target(self, target: Uf2TargetInfo) -> None:
        assert self._downloaded_variants

        whole_mapping = {self._create_variant_description(v): v for v in self._downloaded_variants}

        if target.family is not None:
            filtered_mapping = {
                item[0]: item[1]
                for item in whole_mapping.items()
                if item[1]["family"].startswith(target.family)
            }
            if not filtered_mapping:
                filtered_mapping = whole_mapping
        else:
            filtered_mapping = whole_mapping

        prev_variant = self._variant_combo.get_selected_value()

        self._variant_combo.set_mapping(filtered_mapping)
        matches = list(
            filter(
                lambda v: self._variant_is_meant_for_target(v, target), filtered_mapping.values()
            )
        )

        if len(matches) == 1:
            self._variant_combo.select_value(matches[0])
        elif prev_variant and prev_variant in filtered_mapping.values():
            self._variant_combo.select_value(prev_variant)

    def _handle_new_variant(self, variant: Dict[str, Any]) -> None:
        versions_mapping = {d["version"]: d["url"] for d in variant["downloads"]}
        self._version_combo.set_mapping(versions_mapping)
        if len(versions_mapping) > 0:
            self._version_combo.select_value(list(versions_mapping.values())[0])
        else:
            self._version_combo.select_none()

    def _create_variant_description(self, variant: Dict[str, Any]) -> str:
        return variant["vendor"] + " • " + variant.get("title", variant["model"])

    def _variant_is_meant_for_target(self, variant: Dict[str, Any], target: Uf2TargetInfo):
        if target.family is None:
            # Don't assume anything about unknown targets
            return False

        if not variant["family"].startswith(target.family):
            return False

        if target.model is None:
            return False

        # Compare set of words both with and without considering the possibility that one of them
        # may have vendor name added and other not.
        return self._extract_normalized_words(target.model) == self._extract_normalized_words(
            variant["model"]
        ) or self._extract_normalized_words(
            target.model + " " + variant["vendor"]
        ) == self._extract_normalized_words(
            variant["model"] + " " + variant["vendor"]
        )

    def _extract_normalized_words(self, text: str) -> Set[str]:
        return set(text.replace("_", " ").replace("-", "").lower().split())

    def _describe_target_path(self, path: str) -> str:
        if sys.platform == "win32":
            try:
                label = get_win_volume_name(path)
                disk = path.strip("\\")
                return f"{label} ({disk})"
            except:
                logger.error("Could not query volume name for %r", path)
                return path
        else:
            return path

    def _create_target_info(self, path: str) -> Uf2TargetInfo:
        info_path = os.path.join(path, "INFO_UF2.TXT")
        assert os.path.isfile(info_path)
        with open(info_path, encoding="utf-8") as fp:
            info_content = fp.read()
        info_lines = info_content.splitlines()
        normalized_content = info_content.lower().replace(" ", "").replace("_", "").replace("-", "")

        model = find_uf2_property(info_lines, "Model")
        board_id = find_uf2_property(info_lines, "Board-ID")

        if "boardid:rpirp2" in normalized_content:
            family = "rp2"
        else:
            for keyword in ["samd21", "samd51", "nrf51", "nrf52", "esp32s3", "esp32s3"]:
                if keyword in normalized_content:
                    family = keyword
                    break
            else:
                family = None

        return Uf2TargetInfo(
            title=self._describe_target_path(path),
            path=path,
            family=family,
            model=model,
            board_id=board_id,
        )

    def _download_variants(self):
        logger.info("Downloading %r", self._get_variants_url())
        import json
        from urllib.request import urlopen

        try:
            req = urllib.request.Request(
                self._get_variants_url(),
                data=None,
                headers={
                    "User-Agent": FAKE_USER_AGENT,
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(req) as fp:
                json_str = fp.read().decode("UTF-8")
                # logger.debug("Variants info: %r", json_str)
            self._downloaded_variants = json.loads(json_str)
            logger.info("Got %r variants", len(self._downloaded_variants))
        except Exception:
            msg = f"Could not download variants info from {self._get_variants_url()}"
            logger.exception(msg)
            self.append_text(msg + "\n")
            self.set_action_text("Error!")
            self.grid_progress_widgets()

    def get_ok_text(self):
        return tr("Install")

    def get_instructions(self) -> Optional[str]:
        return (
            "Here you can install or update MicroPython for devices having an UF2 bootloader\n"
            "(this includes most boards meant for beginners).\n"
            "\n"
            "1. Put your device into bootloader mode: \n"
            "     - some devices have to be plugged in while holding the BOOTSEL button,\n"
            "     - some require double-tapping the RESET button with proper rythm.\n"
            "2. Wait for couple of seconds until the target volume appears.\n"
            "3. Select desired variant and version.\n"
            "4. Click 'Install' and wait for some seconds until done.\n"
            "5. Close the dialog and start programming!"
        )

    def _on_variant_select(self, *args):
        pass


def find_uf2_property(lines: List[str], prop_name: str) -> Optional[str]:
    marker = prop_name + ": "
    for line in lines:
        if line.startswith(marker):
            return line[len(marker) :]

    return None