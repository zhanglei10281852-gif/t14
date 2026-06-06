import logging
from typing import List, Optional
from plant_model import (
    PlantState,
    CellState,
    PurifierState,
    PumpState,
    create_plant_state,
)
from config import PlantConfig
from scheduler import Scheduler, manage_tank_filling
from interlock import InterlockSystem
from recorder import Recorder
from reporter import Reporter


logger = logging.getLogger(__name__)


class Simulator:
    def __init__(self, config: PlantConfig):
        self.config = config
        self.state: PlantState = create_plant_state(config)
        self.scheduler = Scheduler(config)
        self.interlock = InterlockSystem(config)
        self.recorder = Recorder(
            csv_file=config.recorder.csv_file,
            history_file=config.recorder.history_file,
        )
        self.reporter = Reporter(config)
        self.current_schedule: List[dict] = []
        self.pending_commands: List[dict] = []
        self.auto_mode = False
        self.max_steps = config.general.max_steps

    def initialize(self) -> None:
        self.state.step = self.config.general.initial_step
        self._update_schedule()

    def _update_schedule(self) -> None:
        self.current_schedule = self.scheduler.generate_schedule(
            self.state, self.state.target_demand
        )

    def step(self) -> None:
        self.state.step += 1

        self._process_commands()
        self._advance_cell_state_machines()
        self._update_loads()
        self._update_rectifiers()

        self.interlock.auto_reset_level1(self.state)
        self.interlock.check_all_interlocks(self.state)

        self._update_temperatures()
        self._update_h2_concentration()
        self._manage_purifiers()
        manage_tank_filling(self.state)
        self._update_tanks_relief()
        self._update_cooling_water()

        self._update_energy()
        self._update_run_time()

        self.recorder.record_step(self.state)

        if self.state.step % 5 == 0:
            self._update_schedule()

    def _process_commands(self) -> None:
        for cmd in self.pending_commands:
            action = cmd.get("action")
            if action in ("start_purge", "start_warmup", "start_running",
                           "set_load", "stop", "emergency_stop", "reset"):
                self.scheduler.apply_command(self.state, cmd)
        self.pending_commands = []

        for plan_item in self.current_schedule:
            if plan_item.get("step_offset", 0) == 0:
                self.scheduler.apply_command(self.state, plan_item)

    def _advance_cell_state_machines(self) -> None:
        for cell in self.state.electrolyzers.values():
            cell.state_timer += 1

            if cell.state == CellState.N2_PURGE:
                if cell.state_timer >= cell.cfg.n2_purge_time:
                    cell.state = CellState.WARMUP
                    cell.state_timer = 0
                    self.state.add_interlock_log_entry(
                        "info", cell.cfg.id, "warmup_start", "n2_purge_complete"
                    )

            elif cell.state == CellState.WARMUP:
                if cell.state_timer >= cell.cfg.warmup_time:
                    cell.state = CellState.RUNNING
                    cell.load_ratio = cell.min_load_ratio
                    cell.target_load_ratio = cell.min_load_ratio
                    cell.state_timer = 0
                    self.state.add_interlock_log_entry(
                        "info", cell.cfg.id, "start_running", "warmup_complete"
                    )

    def _update_loads(self) -> None:
        for cell in self.state.electrolyzers.values():
            cell.update_load()
            cell.calc_output()

    def _update_temperatures(self) -> None:
        for cell in self.state.electrolyzers.values():
            cell.update_temp(self.state.cooling_water_temp)

    def _update_h2_concentration(self) -> None:
        if self.state.ventilation_active:
            decay_rate = self.config.safety.ventilation_rate * 2
            self.state.h2_concentration = max(0.0, self.state.h2_concentration - decay_rate)
        else:
            self.state.h2_concentration = max(0.0, self.state.h2_concentration * 0.995)

    def _manage_purifiers(self) -> None:
        total_output = sum(
            c.h2_output
            for c in self.state.electrolyzers.values()
            if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING)
        )

        active_purifiers = [
            p for p in self.state.purifiers.values() if p.state == PurifierState.ACTIVE
        ]

        if total_output > 0 and not active_purifiers:
            standby = [
                p for p in self.state.purifiers.values() if p.state == PurifierState.STANDBY
            ]
            if standby:
                standby[0].activate()

        if total_output == 0 and active_purifiers:
            for p in active_purifiers:
                p.deactivate()

        for purifier in self.state.purifiers.values():
            if purifier.state == PurifierState.ACTIVE:
                purifier.process(total_output)

    def _update_tanks_relief(self) -> None:
        for tank in self.state.tanks.values():
            if tank.is_relieving:
                tank.relief()

    def _update_cooling_water(self) -> None:
        pumps = self.state.cooling_pumps
        active_pumps = [p for p in pumps.values() if p.state == PumpState.ACTIVE]
        ambient = self.config.cooling_system.ambient_temp

        if active_pumps:
            heat_load = sum(
                c.load_ratio * 0.3
                for c in self.state.electrolyzers.values()
                if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING)
            )
            target_temp = ambient + heat_load * 2
            if len(active_pumps) >= 1:
                target_temp -= self.config.cooling_system.pump_heat_removal
            self.state.cooling_water_temp += (target_temp - self.state.cooling_water_temp) * 0.1
        else:
            self.state.cooling_water_temp += (ambient + 5 - self.state.cooling_water_temp) * 0.05

    def _update_rectifiers(self) -> None:
        for rect_id, rectifier in self.state.rectifiers.items():
            cell_id = rectifier.cfg.paired_cell
            if cell_id in self.state.electrolyzers:
                cell = self.state.electrolyzers[cell_id]
                if not rectifier.is_tripped:
                    rectifier.output_current = cell.current
                else:
                    cell.current = 0.0
                    if cell.state == CellState.RUNNING:
                        cell.emergency_stop("rectifier_trip")

    def _update_energy(self) -> None:
        total_power_kw = sum(
            c.power
            for c in self.state.electrolyzers.values()
            if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING)
        )
        self.state.total_energy_kwh += total_power_kw / 60.0

    def _update_run_time(self) -> None:
        for cell in self.state.electrolyzers.values():
            if cell.state in (CellState.RUNNING, CellState.LOAD_REDUCING):
                cell.run_time_total += 1

    def set_demand(self, demand: float) -> None:
        self.state.target_demand = demand
        self._update_schedule()
        logger.info(f"目标产量设置为 {demand} Nm³/h")

    def inject_h2_leak(self, concentration: float) -> None:
        self.state.h2_concentration = concentration
        logger.warning(f"注入氢气泄漏事件: {concentration*100:.2f}% vol")

    def set_tank_pressure(self, tank_id: str, pressure: float) -> None:
        if tank_id in self.state.tanks:
            self.state.tanks[tank_id].pressure = pressure
            logger.warning(f"设置 {tank_id} 压力设为 {pressure} MPa")

    def set_pump_state(self, pump_id: str, state_str: str) -> None:
        if pump_id in self.state.cooling_pumps:
            pump = self.state.cooling_pumps[pump_id]
            if state_str == "fault":
                pump.set_fault()
                logger.warning(f"{pump_id} 故障")
                active_count = sum(
                    1
                    for p in self.state.cooling_pumps.values()
                    if p.state == PumpState.ACTIVE
                )
                if active_count == 0:
                    standby = [
                        p
                        for p in self.state.cooling_pumps.values()
                        if p.state == PumpState.STANDBY
                    ]
                    if standby:
                        standby[0].start()
                        logger.info(f"自动启动备用泵: {standby[0].cfg.id}")
            elif state_str == "active":
                if pump.state == PumpState.FAULT:
                    pump.reset_fault()
                pump.start()
                logger.info(f"{pump_id} 启动")

    def trigger_fire_alarm(self) -> None:
        self.state.fire_alarm_active = True
        logger.critical("火灾报警触发!")

    def reset_device(self, device_id: str) -> bool:
        result = self.interlock.reset_level2_device(self.state, device_id)
        if result:
            logger.info(f"设备 {device_id} 已复位")
        else:
            logger.warning(f"设备 {device_id} 复位失败")
        return result

    def reset_esd(self, code: str) -> bool:
        result = self.interlock.reset_esd(self.state, code)
        if result:
            logger.info("ESD已复位")
        else:
            logger.warning("ESD复位失败，确认码错误")
        return result

    def get_status_text(self) -> str:
        return self._format_status_plain()

    def _format_status_plain(self) -> str:
        lines = []
        lines.append(f"=== 第 {self.state.step} 步 ===")
        lines.append(f"目标产量: {self.state.target_demand:.1f} Nm³/h")
        lines.append(
            f"实际总产氢: {sum(c.h2_output for c in self.state.electrolyzers.values()):.1f} Nm³/h"
        )
        lines.append(f"氢气浓度: {self.state.h2_concentration*100:.3f}% vol")
        lines.append(f"冷却水温度: {self.state.cooling_water_temp:.1f} ℃")
        lines.append(f"累计产氢: {self.state.total_h2_produced:.2f} Nm³")
        lines.append(f"累计能耗: {self.state.total_energy_kwh:.2f} kWh")
        if self.state.esd_active:
            lines.append(f"*** ESD激活! 复位码: {self.state.esd_reset_code}")
        if self.state.level1_alarms:
            lines.append(f"一级告警: {', '.join(self.state.level1_alarms)}")
        if self.state.level2_alarms:
            lines.append(f"二级告警: {', '.join(self.state.level2_alarms)}")
        lines.append("")

        lines.append("--- 电解槽状态 ---")
        for cid, cell in self.state.electrolyzers.items():
            lines.append(
                f"  {cid}: {cell.state.value:<15} 负荷={cell.load_ratio*100:5.1f}%  "
                f"产氢={cell.h2_output:6.1f} Nm³/h  温度={cell.electrolyte_temp:5.1f}℃  "
                f"运行={cell.run_time_total}min"
            )
        lines.append("")

        lines.append("--- 储罐状态 ---")
        for tid, tank in self.state.tanks.items():
            status = []
            if tank.is_filling:
                status.append("充装中")
            if tank.is_relieving:
                status.append("泄压中")
            status_str = "/".join(status) if status else "闲置"
            lines.append(
                f"  {tid}: {tank.pressure:5.1f} MPa / {tank.cfg.design_pressure:.0f} MPa  "
                f"充装速率={tank.fill_rate:5.1f} Nm³/h  [{status_str}]"
            )
        lines.append("")

        lines.append("--- 冷却水泵 ---")
        for pid, pump in self.state.cooling_pumps.items():
            lines.append(f"  {pid}: {pump.state.value}")
        lines.append("")

        return "\n".join(lines)

    def get_history_text(self, n: int) -> str:
        history = self.recorder.get_recent_history(n)
        if not history:
            return "无历史数据"
        lines = [f"最近 {len(history)} 步历史:"]
        for h in history:
            total_out = h.get("total_h2_output", 0)
            lines.append(
                f"  第{h['step']:3d}步: 产氢={total_out:6.1f} Nm³/h  "
                f"H2浓度={h['h2_concentration']*100:.3f}%  "
                f"水温={h['cooling_water_temp']:.1f}℃"
            )
        return "\n".join(lines)

    def get_report(self) -> str:
        return self.reporter.generate_report(self.state, self.recorder)

    def save_report(self) -> None:
        self.reporter.save_report(self.state, self.recorder)
        self.recorder.save_history_json()

    def run_n_steps(self, n: int) -> None:
        for _ in range(n):
            if self.state.step >= self.max_steps:
                break
            self.step()
