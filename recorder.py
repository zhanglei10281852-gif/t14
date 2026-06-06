import csv
import json
from pathlib import Path
from typing import List, Dict
from plant_model import PlantState


class Recorder:
    def __init__(self, csv_file: str = "simulation_data.csv", history_file: str = "simulation_history.json"):
        self.csv_file = csv_file
        self.history_file = history_file
        self.csv_headers: List[str] = []
        self._csv_initialized = False
        self.history: List[dict] = []

    def _init_csv(self, state: PlantState) -> None:
        headers = ["step", "time_min", "target_demand", "total_h2_output", "total_energy_kwh",
                   "h2_concentration", "cooling_water_temp", "ventilation_active",
                   "esd_active", "fire_alarm_active"]

        for cell_id in state.electrolyzers:
            headers.extend([
                f"{cell_id}_state",
                f"{cell_id}_load_ratio",
                f"{cell_id}_h2_output",
                f"{cell_id}_power",
                f"{cell_id}_current",
                f"{cell_id}_electrolyte_temp",
                f"{cell_id}_run_time",
            ])

        for tank_id in state.tanks:
            headers.extend([
                f"{tank_id}_pressure",
                f"{tank_id}_fill_rate",
                f"{tank_id}_is_filling",
                f"{tank_id}_is_relieving",
            ])

        for pump_id in state.cooling_pumps:
            headers.extend([
                f"{pump_id}_state",
                f"{pump_id}_flow_rate",
            ])

        self.csv_headers = headers
        self._csv_initialized = True

        with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    def record_step(self, state: PlantState) -> None:
        if not self._csv_initialized:
            self._init_csv(state)

        row_data = {
            "step": state.step,
            "time_min": state.step,
            "target_demand": state.target_demand,
            "total_h2_output": sum(c.h2_output for c in state.electrolyzers.values()),
            "total_energy_kwh": state.total_energy_kwh,
            "h2_concentration": state.h2_concentration,
            "cooling_water_temp": state.cooling_water_temp,
            "ventilation_active": state.ventilation_active,
            "esd_active": state.esd_active,
            "fire_alarm_active": state.fire_alarm_active,
        }

        for cell_id, cell in state.electrolyzers.items():
            row_data[f"{cell_id}_state"] = cell.state.value
            row_data[f"{cell_id}_load_ratio"] = cell.load_ratio
            row_data[f"{cell_id}_h2_output"] = cell.h2_output
            row_data[f"{cell_id}_power"] = cell.power
            row_data[f"{cell_id}_current"] = cell.current
            row_data[f"{cell_id}_electrolyte_temp"] = cell.electrolyte_temp
            row_data[f"{cell_id}_run_time"] = cell.run_time_total

        for tank_id, tank in state.tanks.items():
            row_data[f"{tank_id}_pressure"] = tank.pressure
            row_data[f"{tank_id}_fill_rate"] = tank.fill_rate
            row_data[f"{tank_id}_is_filling"] = tank.is_filling
            row_data[f"{tank_id}_is_relieving"] = tank.is_relieving

        for pump_id, pump in state.cooling_pumps.items():
            row_data[f"{pump_id}_state"] = pump.state.value
            row_data[f"{pump_id}_flow_rate"] = pump.flow_rate

        self.history.append(row_data.copy())

        with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([row_data.get(h, "") for h in self.csv_headers])

    def get_recent_history(self, n: int) -> List[dict]:
        return self.history[-n:] if n > 0 else []

    def save_history_json(self) -> None:
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def get_max_h2_concentration(self) -> float:
        if not self.history:
            return 0.0
        return max(h["h2_concentration"] for h in self.history)

    def get_max_tank_pressure(self) -> Dict[str, float]:
        result = {}
        if not self.history:
            return result
        tank_keys = [k for k in self.history[0].keys() if k.endswith("_pressure") and k.startswith("tank")]
        for key in tank_keys:
            result[key] = max(h[key] for h in self.history)
        return result

    def get_interlock_count(self, state: PlantState) -> Dict[str, Dict[str, int]]:
        level_counts = {"level1": {}, "level2": {}, "level3": {}}
        for entry in state.interlock_log:
            level = entry["level"]
            device = entry["device"]
            if level in level_counts:
                if device not in level_counts[level]:
                    level_counts[level][device] = 0
                level_counts[level][device] += 1
        return level_counts
