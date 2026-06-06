from typing import List, Dict, Tuple
from plant_model import PlantState, Electrolyzer, Tank, CellState, AlarmLevel
from config import PlantConfig, SafetyConfig
import random


class InterlockSystem:
    def __init__(self, config: PlantConfig):
        self.config = config
        self.safety_cfg = config.safety

    def check_all_interlocks(self, state: PlantState) -> Dict[str, List[str]]:
        """执行所有安全联锁检查，返回触发的告警"""
        triggered = {
            "level1": [],
            "level2": [],
            "level3": [],
        }

        if state.esd_active:
            return triggered

        h2_alarms = self.check_h2_concentration(state)
        for level, alarms in h2_alarms.items():
            triggered[level].extend(alarms)

        temp_alarms = self.check_electrolyte_temp(state)
        for level, alarms in temp_alarms.items():
            triggered[level].extend(alarms)

        cooling_alarms = self.check_cooling_water(state)
        for level, alarms in cooling_alarms.items():
            triggered[level].extend(alarms)

        rectifier_alarms = self.check_rectifiers(state)
        for level, alarms in rectifier_alarms.items():
            triggered[level].extend(alarms)

        tank_alarms = self.check_tanks(state)
        for level, alarms in tank_alarms.items():
            triggered[level].extend(alarms)

        fire_alarms = self.check_fire_alarm(state)
        for level, alarms in fire_alarms.items():
            triggered[level].extend(alarms)

        return triggered

    def check_h2_concentration(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}
        h2 = state.h2_concentration

        if h2 >= self.safety_cfg.h2_lel_three:
            triggered["level3"].append("h2_concentration_lel_100")
            self._trigger_esd(state, "h2_concentration_exceeds_lel_100")
        elif h2 >= self.safety_cfg.h2_lel_two:
            triggered["level2"].append("h2_concentration_lel_50")
            self._h2_level2_action(state)
        elif h2 >= self.safety_cfg.h2_lel_one:
            triggered["level1"].append("h2_concentration_lel_25")
            self._h2_level1_action(state)
        else:
            if state.ventilation_active:
                state.ventilation_active = False

        return triggered

    def _h2_level1_action(self, state: PlantState) -> None:
        state.ventilation_active = True
        for cell in state.electrolyzers.values():
            if cell.state == CellState.RUNNING:
                if cell.target_load_ratio > cell.load_ratio:
                    cell.target_load_ratio = cell.load_ratio
        if "h2_leak_level1" not in state.level1_alarms:
            state.level1_alarms.append("h2_leak_level1")
            state.add_interlock_log_entry("level1", "plant", "ventilation_start", "h2_concentration_warning")

    def _h2_level2_action(self, state: PlantState) -> None:
        state.ventilation_active = True
        for cell in state.electrolyzers.values():
            if cell.state in (CellState.RUNNING, CellState.LOAD_REDUCING):
                cell.emergency_stop("h2_concentration_high")
        for purifier in state.purifiers.values():
            purifier.deactivate()
        if "h2_leak_level2" not in state.level2_alarms:
            state.level2_alarms.append("h2_leak_level2")
            state.add_interlock_log_entry("level2", "plant", "emergency_shutdown", "h2_concentration_critical")

    def _trigger_esd(self, state: PlantState, reason: str) -> None:
        if state.esd_active:
            return
        state.esd_active = True
        state.esd_reset_code = str(random.randint(1000, 9999))
        for cell in state.electrolyzers.values():
            if cell.state != CellState.STOPPED:
                cell.emergency_stop(f"esd_{reason}")
        for purifier in state.purifiers.values():
            purifier.deactivate()
        for rectifier in state.rectifiers.values():
            rectifier.trip(f"esd_{reason}")
        state.add_interlock_log_entry("level3", "plant", "esd_triggered", reason)
        if "esd" not in state.level3_alarms:
            state.level3_alarms.append("esd")

    def check_electrolyte_temp(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}

        for cell_id, cell in state.electrolyzers.items():
            if cell.state not in (CellState.RUNNING, CellState.LOAD_REDUCING):
                continue

            if cell.electrolyte_temp >= cell.cfg.electrolyte_temp_trip:
                triggered["level2"].append(f"{cell_id}_temp_trip")
                if f"{cell_id}_temp_trip" not in state.level2_alarms:
                    cell.emergency_stop("electrolyte_temp_high")
                    state.level2_alarms.append(f"{cell_id}_temp_trip")
                    state.add_interlock_log_entry("level2", cell_id, "emergency_stop", "electrolyte_temp_trip")
            elif cell.electrolyte_temp >= cell.cfg.electrolyte_temp_alarm:
                triggered["level1"].append(f"{cell_id}_temp_alarm")
                cell.load_limit_ratio = min(cell.load_limit_ratio, 0.8)
                if f"{cell_id}_temp_alarm" not in state.level1_alarms:
                    state.level1_alarms.append(f"{cell_id}_temp_alarm")
                    state.add_interlock_log_entry("level1", cell_id, "load_limit_80", "electrolyte_temp_high")

        return triggered

    def check_cooling_water(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}

        cw_temp = state.cooling_water_temp
        alarm_temp = self.config.cooling_system.cooling_water_temp_alarm

        if cw_temp >= alarm_temp:
            triggered["level1"].append("cooling_water_temp_high")
            for cell in state.electrolyzers.values():
                cell.load_limit_ratio = min(cell.load_limit_ratio, 0.7)
            if "cooling_water_temp_high" not in state.level1_alarms:
                state.level1_alarms.append("cooling_water_temp_high")
                state.add_interlock_log_entry("level1", "cooling_system", "load_limit_70", "cooling_water_temp_high")
        else:
            for cell in state.electrolyzers.values():
                cell.load_limit_ratio = 1.0

        return triggered

    def check_rectifiers(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}

        for rect_id, rectifier in state.rectifiers.items():
            cell_id = rectifier.cfg.paired_cell
            if cell_id not in state.electrolyzers:
                continue
            cell = state.electrolyzers[cell_id]
            rated_current = cell.cfg.rated_current
            overload_ratio = rectifier.cfg.overload_protection_ratio

            if cell.current > rated_current * overload_ratio:
                triggered["level2"].append(f"{rect_id}_overload")
                if not rectifier.is_tripped:
                    rectifier.trip("overcurrent")
                    cell.emergency_stop("rectifier_overcurrent")
                    if f"{rect_id}_overcurrent" not in state.level2_alarms:
                        state.level2_alarms.append(f"{rect_id}_overcurrent")
                        state.add_interlock_log_entry("level2", rect_id, "trip", "overcurrent_protection")

        return triggered

    def check_tanks(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}

        for tank_id, tank in state.tanks.items():
            if tank.pressure >= tank.cfg.trip_pressure:
                triggered["level2"].append(f"{tank_id}_pressure_trip")
                if not tank.is_relieving:
                    tank.is_relieving = True
                    tank.is_filling = False
                    if f"{tank_id}_pressure_trip" not in state.level2_alarms:
                        state.level2_alarms.append(f"{tank_id}_pressure_trip")
                        state.add_interlock_log_entry("level2", tank_id, "emergency_relief", "pressure_trip")
            elif tank.pressure >= tank.cfg.alarm_pressure:
                triggered["level1"].append(f"{tank_id}_pressure_alarm")
                if tank.is_filling:
                    tank.is_filling = False
                if f"{tank_id}_pressure_alarm" not in state.level1_alarms:
                    state.level1_alarms.append(f"{tank_id}_pressure_alarm")
                    state.add_interlock_log_entry("level1", tank_id, "stop_filling", "pressure_high_alarm")

        return triggered

    def check_fire_alarm(self, state: PlantState) -> Dict[str, List[str]]:
        triggered = {"level1": [], "level2": [], "level3": []}

        if state.fire_alarm_active:
            triggered["level3"].append("fire_alarm")
            self._trigger_esd(state, "fire_alarm")

        return triggered

    def reset_level1_alarm(self, state: PlantState, alarm_id: str) -> bool:
        if alarm_id in state.level1_alarms:
            state.level1_alarms.remove(alarm_id)
            return True
        return False

    def reset_level2_device(self, state: PlantState, device_id: str) -> bool:
        if device_id in state.electrolyzers:
            cell = state.electrolyzers[device_id]
            if cell.state in (CellState.EMERGENCY_STOP, CellState.FAULT):
                if cell.electrolyte_temp < cell.cfg.electrolyte_temp_alarm - 5:
                    cell.reset_from_fault()
                    alarm_key = f"{device_id}_temp_trip"
                    if alarm_key in state.level2_alarms:
                        state.level2_alarms.remove(alarm_key)
                    alarm_key = f"{device_id}_temp_alarm"
                    if alarm_key in state.level1_alarms:
                        state.level1_alarms.remove(alarm_key)
                    state.add_interlock_log_entry("level2", device_id, "reset", "manual_reset")
                    return True
        if device_id in state.rectifiers:
            rectifier = state.rectifiers[device_id]
            if rectifier.is_tripped:
                rectifier.reset()
                alarm_key = f"{device_id}_overcurrent"
                if alarm_key in state.level2_alarms:
                    state.level2_alarms.remove(alarm_key)
                cell_id = rectifier.cfg.paired_cell
                if cell_id in state.electrolyzers:
                    cell = state.electrolyzers[cell_id]
                    if cell.state == CellState.EMERGENCY_STOP:
                        cell.reset_from_fault()
                state.add_interlock_log_entry("level2", device_id, "reset", "manual_reset")
                return True
        return False

    def reset_esd(self, state: PlantState, code: str) -> bool:
        if not state.esd_active:
            return False
        if code == state.esd_reset_code:
            state.esd_active = False
            state.esd_reset_code = ""
            state.fire_alarm_active = False
            if "esd" in state.level3_alarms:
                state.level3_alarms.remove("esd")
            if "fire_alarm" in state.level3_alarms:
                state.level3_alarms.remove("fire_alarm")
            for cell in state.electrolyzers.values():
                if cell.state == CellState.EMERGENCY_STOP:
                    cell.reset_from_fault()
            for rectifier in state.rectifiers.values():
                if rectifier.is_tripped:
                    rectifier.reset()
            state.add_interlock_log_entry("level3", "plant", "esd_reset", "manual_esd_reset")
            return True
        return False

    def auto_reset_level1(self, state: PlantState) -> None:
        if state.h2_concentration < self.safety_cfg.h2_lel_one * 0.8:
            if "h2_leak_level1" in state.level1_alarms:
                state.level1_alarms.remove("h2_leak_level1")
                state.add_interlock_log_entry("level1", "plant", "auto_clear", "h2_concentration_normal")

        if state.cooling_water_temp < self.config.cooling_system.cooling_water_temp_alarm - 3:
            if "cooling_water_temp_high" in state.level1_alarms:
                state.level1_alarms.remove("cooling_water_temp_high")
                for cell in state.electrolyzers.values():
                    cell.load_limit_ratio = 1.0
                state.add_interlock_log_entry("level1", "cooling_system", "auto_clear", "cooling_water_temp_normal")

        for cell_id, cell in state.electrolyzers.items():
            alarm_key = f"{cell_id}_temp_alarm"
            if alarm_key in state.level1_alarms:
                if cell.electrolyte_temp < cell.cfg.electrolyte_temp_alarm - 3:
                    state.level1_alarms.remove(alarm_key)
                    state.add_interlock_log_entry("level1", cell_id, "auto_clear", "temp_normal")

        for tank_id, tank in state.tanks.items():
            alarm_key = f"{tank_id}_pressure_alarm"
            if alarm_key in state.level1_alarms:
                if tank.pressure < tank.cfg.alarm_pressure - 1:
                    state.level1_alarms.remove(alarm_key)
                    state.add_interlock_log_entry("level1", tank_id, "auto_clear", "pressure_normal")
