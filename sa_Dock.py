# -*- coding: utf-8 -*-

import os
from typing import Optional, Dict, Any, List, Tuple, Set

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

# Internal lists/vars
# _COMMAND_LIST becomes a list of dicts:
#   { "name": <command-name>, "text": <button label or None>, "tooltip": <override or None> }
# where "Separator" (or "separator") is represented as { "name": "separator", ... }
_COMMAND_LIST: List[Dict[str, Optional[str]]] = []
_MENU_LIST: List[Any] = []
_REMOVED = set()

DOCK_OBJECT_NAME = "OpticsWorkbench_Dock_SA"
DOCK_WINDOW_TITLE = "Optics Dock SA"


def set_command_lists(list_commands, list_menu, remove_command=None):
    """
    Accepts the same list that's built in Initialize() and normalizes it for the dock.
    - Allows:
        * strings (incl. "Separator"/"separator")
        * dicts with {"name"/"command"/"cmd", "text"/"label", "tooltip"/"tip"}
        * tuple/list: (name, [text], [tooltip])
    - remove_command: str or iterable of strings
    """
    global _COMMAND_LIST, _MENU_LIST, _REMOVED

    commands_in = list(list_commands) if list_commands else []
    menu = list(list_menu) if list_menu else []

    if remove_command is None:
        to_remove = set()
    elif isinstance(remove_command, str):
        to_remove = {remove_command}
    else:
        try:
            to_remove = {x for x in remove_command if isinstance(x, str)}
        except TypeError:
            to_remove = set()

    def _normalize(cmd):
        # Support "Separator"/"separator" in the list
        def _is_separator(s: str) -> bool:
            return isinstance(s, str) and s.strip().lower() == "separator"

        if isinstance(cmd, str):
            if _is_separator(cmd):
                return {"name": "separator", "text": None, "tooltip": None}
            if cmd in to_remove:
                return None
            return {"name": cmd, "text": None, "tooltip": None}

        if isinstance(cmd, dict):
            # allow multiple key names for the command
            name = cmd.get("name") or cmd.get("command") or cmd.get("cmd")
            if not isinstance(name, str):
                return None
            if name in to_remove:
                return None
            if _is_separator(name):
                return {"name": "separator", "text": None, "tooltip": None}
            return {
                "name": name,
                "text": cmd.get("text") or cmd.get("label"),
                "tooltip": cmd.get("tooltip") or cmd.get("tip"),
            }

        if isinstance(cmd, (tuple, list)) and cmd:
            name = cmd[0]
            if not isinstance(name, str):
                return None
            if name in to_remove:
                return None
            if _is_separator(name):
                return {"name": "separator", "text": None, "tooltip": None}
            # (name, text?, tooltip?)
            text = cmd[1] if len(cmd) > 1 and isinstance(cmd[1], str) else None
            tooltip = cmd[2] if len(cmd) > 2 and isinstance(cmd[2], str) else None
            return {"name": name, "text": text, "tooltip": tooltip}

        # unknown format – ignore
        return None

    normalized: List[Dict[str, Optional[str]]] = []
    for c in commands_in:
        nc = _normalize(c)
        if nc is not None:
            normalized.append(nc)

    _COMMAND_LIST = normalized
    _MENU_LIST = menu
    _REMOVED = to_remove


def _module_path():
    try:
        import sa_OpticsWorkbench

        return sa_OpticsWorkbench.get_module_path()
    except Exception:
        return os.path.dirname(__file__)


def _icon_path():
    return os.path.join(_module_path(), "optics_workbench_icon.svg")


# --- QAction-based resource retrieval (strict and filtered) -------------------


def _command_name_set() -> Set[str]:
    """Set of command names from _COMMAND_LIST (excluding separators)."""
    return {it["name"] for it in _COMMAND_LIST if isinstance(it, dict) and isinstance(it.get("name"), str) and it["name"].lower() != "separator"}


def _strict_match_action(action: QtWidgets.QAction, cmd_name: str) -> bool:
    """
    Strictly match QAction to command:
      - objectName == cmd_name  OR
      - action.data() == cmd_name (if data is a string)
    """
    try:
        if action.objectName() == cmd_name:
            return True
    except Exception:
        pass
    try:
        d = action.data()
        if isinstance(d, str) and d == cmd_name:
            return True
    except Exception:
        pass
    return False


def _candidate_toolbars() -> List[QtWidgets.QToolBar]:
    """
    Toolbars that contain at least one QAction matching any of our command names (strict).
    This avoids relying on localized toolbar title and prevents cross-workbench bleed.
    """
    mw = Gui.getMainWindow()
    if mw is None:
        return []
    names = _command_name_set()
    out: List[QtWidgets.QToolBar] = []
    seen = set()
    try:
        for tb in mw.findChildren(QtWidgets.QToolBar) or []:
            try:
                acts = tb.actions()
            except Exception:
                continue
            # Count strict matches
            match = False
            for a in acts or []:
                for n in names:
                    if _strict_match_action(a, n):
                        match = True
                        break
                if match:
                    break
            if match:
                key = id(tb)
                if key not in seen:
                    seen.add(key)
                    out.append(tb)
    except Exception:
        pass
    return out


def _candidate_menus() -> List[QtWidgets.QMenu]:
    """
    Menus that contain at least one QAction matching any of our command names (strict).
    """
    mw = Gui.getMainWindow()
    if mw is None:
        return []
    names = _command_name_set()
    out: List[QtWidgets.QMenu] = []
    seen = set()
    try:
        for menu in mw.findChildren(QtWidgets.QMenu) or []:
            try:
                acts = menu.actions()
            except Exception:
                continue
            match = False
            for a in acts or []:
                # include first level and one submenu level
                subacts = [a]
                try:
                    sub = a.menu()
                    if isinstance(sub, QtWidgets.QMenu):
                        subacts.extend(sub.actions() or [])
                except Exception:
                    pass
                # any strict match
                for sa in subacts:
                    for n in names:
                        if _strict_match_action(sa, n):
                            match = True
                            break
                    if match:
                        break
                if match:
                    break
            if match:
                key = id(menu)
                if key not in seen:
                    seen.add(key)
                    out.append(menu)
    except Exception:
        pass
    return out


def _optics_actions() -> List[QtWidgets.QAction]:
    """
    Union of QActions found in candidate toolbars/menus that contain our commands.
    De-duplicated while preserving order.
    """
    actions: List[QtWidgets.QAction] = []
    seen = set()
    for tb in _candidate_toolbars():
        try:
            for a in tb.actions() or []:
                k = id(a)
                if k not in seen:
                    seen.add(k)
                    actions.append(a)
        except Exception:
            pass
    for m in _candidate_menus():
        try:
            for a in m.actions() or []:
                # include submenu actions one level
                k = id(a)
                if k not in seen:
                    seen.add(k)
                    actions.append(a)
                try:
                    sub = a.menu()
                    if isinstance(sub, QtWidgets.QMenu):
                        for sa in sub.actions() or []:
                            ks = id(sa)
                            if ks not in seen:
                                seen.add(ks)
                                actions.append(sa)
                except Exception:
                    pass
        except Exception:
            pass
    return actions


def _action_for_command(cmd_name: str) -> Optional[QtWidgets.QAction]:
    """
    Find QAction strictly matching cmd_name from the Optics-related toolbars/menus only.
    We DO NOT fall back to global actions to prevent cross-workbench leakage.
    """
    for act in _optics_actions():
        try:
            if _strict_match_action(act, cmd_name):
                return act
        except Exception:
            continue
    return None


def create_or_show_dock():
    mw = Gui.getMainWindow()
    if mw is None:
        App.Console.PrintError("[Optics] FreeCAD main window not found.\n")
        return

    existing = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None:
        existing.show()
        existing.raise_()
        existing.activateWindow()
        return

    dock = DockWidget(parent=mw)
    dock.setObjectName(DOCK_OBJECT_NAME)
    dock.setWindowTitle(DOCK_WINDOW_TITLE)
    dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetClosable)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()


class Optics_ShowDockPanelCmd:
    def GetResources(self):
        return {
            "Pixmap": _icon_path(),
            "MenuText": "Show Dock",
            "ToolTip": "Open the Optics docked panel",
        }

    def Activated(self):
        create_or_show_dock()

    def IsActive(self):
        return True


# Register "Dock" command in FreeCAD
Gui.addCommand("sa_Dock", Optics_ShowDockPanelCmd())


class DockWidget(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Optics Dock", parent)
        central = QtWidgets.QWidget(self)
        self.setWidget(central)

        # Keep track of buttons for later refresh
        self._buttons: List[Tuple[str, QtWidgets.QAbstractButton]] = []  # (cmd_name, button)

        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(10)

        section = self._make_section("Commands")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        row = col = 0
        max_cols = 3

        for item in _COMMAND_LIST:
            # item is dict per normalization
            if item.get("name", "").lower() == "separator":
                if grid.count() > 0:
                    section.layout().addLayout(grid)
                    root.addWidget(section)
                    section = self._make_section("Commands")
                    grid = QtWidgets.QGridLayout()
                    grid.setHorizontalSpacing(8)
                    grid.setVerticalSpacing(6)
                    row = col = 0
                continue

            cmd_name = item["name"]
            label = item.get("text") or cmd_name
            btn = QtWidgets.QPushButton(label, section)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

            # Set preliminary tooltip: override -> label
            pre_tip = item.get("tooltip") or label
            btn.setToolTip(pre_tip)

            # Do not set icon here – we fetch it from QAction after the UI is ready
            btn.clicked.connect(self._make_run_command(cmd_name))
            grid.addWidget(btn, row, col)

            # Save for later refresh
            self._buttons.append((cmd_name, btn))

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        if grid.count() > 0:
            section.layout().addLayout(grid)
            root.addWidget(section)

        root.addStretch(1)

        # Initial delayed attempt to refresh (in case actions appear slightly later)
        self._refresh_attempt = 0
        self._max_refresh_attempts = 5
        self._refresh_interval_ms = 250
        QtCore.QTimer.singleShot(self._refresh_interval_ms, self._refresh_from_actions)

    def showEvent(self, event):
        super().showEvent(event)
        # On show – toolbars/menus should exist
        self._refresh_from_actions()
        # Try again if the dock becomes visible again
        try:
            self.visibilityChanged.connect(self._on_visibility_changed)
        except Exception:
            pass

    def _on_visibility_changed(self, visible: bool):
        if visible:
            self._refresh_from_actions()

    def _refresh_from_actions(self):
        """
        Update icons and tooltips by reading the corresponding QAction
        from candidate Optics toolbar/menu only. No local icon fallback.
        """
        # Build lookup for overrides
        overrides: Dict[str, Dict[str, Optional[str]]] = {}
        for it in _COMMAND_LIST:
            name = it.get("name")
            if name and name.lower() != "separator":
                overrides[name] = {
                    "text": it.get("text"),
                    "tooltip": it.get("tooltip"),
                }

        any_updated = False

        for cmd_name, btn in self._buttons:
            try:
                if not isinstance(btn, QtWidgets.QAbstractButton):
                    continue

                act = _action_for_command(cmd_name)
                if act is None:
                    continue  # try again on next attempt

                # Icon directly from QAction
                icon = act.icon()
                if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                    btn.setIcon(icon)
                    btn.setIconSize(QtCore.QSize(20, 20))
                    any_updated = True

                # Tooltip: override -> QAction.toolTip/statusTip -> existing
                ovr = overrides.get(cmd_name, {})
                tip = ovr.get("tooltip") or act.toolTip() or act.statusTip() or btn.toolTip()
                if isinstance(tip, str):
                    btn.setToolTip(tip)

                # Label: update only if override exists
                lbl = ovr.get("text")
                if isinstance(lbl, str) and lbl and lbl != btn.text():
                    btn.setText(lbl)

            except Exception as e:
                App.Console.PrintError(f"[Optics Dock] Refresh via QAction failed for '{cmd_name}': {e}\n")

        # Retry loop if UI pieces are not yet present
        self._refresh_attempt += 1
        if self._refresh_attempt < self._max_refresh_attempts:
            QtCore.QTimer.singleShot(self._refresh_interval_ms, self._refresh_from_actions)
        else:
            # One last delayed attempt if nothing happened
            if not any_updated:
                QtCore.QTimer.singleShot(1000, self._refresh_from_actions)

    def _make_section(self, title: str):
        box = QtWidgets.QGroupBox(title, self)
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(6)
        return box

    @staticmethod
    def _make_run_command(cmd_name):
        def _run():
            try:
                Gui.runCommand(cmd_name, 0)
            except Exception as e:
                App.Console.PrintError(f"[Optics Dock] Failed to run '{cmd_name}': {e}\n")

        return _run
