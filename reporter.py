from typing import Dict, List
from plant_model import PlantState, CellState
from config import PlantConfig
from recorder import Recorder


class Reporter:
    def __init__(self, config: PlantConfig):
        self.config = config

    def generate_report(self, state: PlantState, recorder: Recorder) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append("            工业制氢站模拟运行统计报告")
        lines.append("=" * 70)
        lines.append("")

        total_steps = state.step
        lines.append(f"【运行概况】")
        lines.append(f"  总运行步数: {total_steps} 步 ({total_steps} 分钟)")
        lines.append(f"  总产氢量: {state.total_h2_produced:.2f} Nm³")
        lines.append(f"  总能耗: {state.total_energy_kwh:.2f} kWh")
        lines.append(f"  平均产氢速率: {state.total_h2_produced / max(total_steps / 60, 1/60):.2f} Nm³/h")
        lines.append("")

        lines.append(f"【电解槽运行统计】")
        for cell_id, cell in state.electrolyzers.items():
            run_hours = cell.run_time_total / 60.0
            utilization = cell.run_time_total / max(total_steps, 1) * 100
            lines.append(f"  {cell.cfg.name} ({cell_id}):")
            lines.append(f"    运行时间: {cell.run_time_total} 分钟 ({run_hours:.2f} 小时)")
            lines.append(f"    利用率: {utilization:.2f}%")
            lines.append(f"    当前状态: {cell.state.value}")
            lines.append(f"    最终负荷: {cell.load_ratio*100:.1f}%")
            lines.append(f"    最终产氢: {cell.h2_output:.1f} Nm³/h")
            lines.append(f"    最终电解液温度: {cell.electrolyte_temp:.1f} ℃")
            lines.append("")

        lines.append(f"【储罐状态】")
        for tank_id, tank in state.tanks.items():
            lines.append(f"  {tank.cfg.name} ({tank_id}):")
            lines.append(f"    最终压力: {tank.pressure:.2f} MPa / {tank.cfg.design_pressure:.0f} MPa")
            lines.append(f"    充装状态: {'充装中' if tank.is_filling else '闲置'} {'泄压中' if tank.is_relieving else ''}")
            lines.append("")

        lines.append(f"【安全联锁动作统计】")
        level_counts = recorder.get_interlock_count(state)
        total_level1 = sum(level_counts.get("level1", {}).values())
        total_level2 = sum(level_counts.get("level2", {}).values())
        total_level3 = sum(level_counts.get("level3", {}).values())

        lines.append(f"  一级报警次数: {total_level1} 次")
        if level_counts.get("level1"):
            for device, count in level_counts["level1"].items():
                lines.append(f"    - {device}: {count} 次")
        lines.append(f"  二级联锁动作次数: {total_level2} 次")
        if level_counts.get("level2"):
            for device, count in level_counts["level2"].items():
                lines.append(f"    - {device}: {count} 次")
        lines.append(f"  三级ESD动作次数: {total_level3} 次")
        if level_counts.get("level3"):
            for device, count in level_counts["level3"].items():
                lines.append(f"    - {device}: {count} 次")
        lines.append("")

        lines.append(f"【极端值记录】")
        max_h2 = recorder.get_max_h2_concentration()
        lines.append(f"  最高氢气浓度: {max_h2*100:.2f}% vol")
        max_pressures = recorder.get_max_tank_pressure()
        for key, val in max_pressures.items():
            tank_name = key.replace("_pressure", "")
            lines.append(f"  最高罐压 ({tank_name}): {val:.2f} MPa")
        lines.append("")

        lines.append(f"【冷却系统】")
        lines.append(f"  冷却水温度: {state.cooling_water_temp:.1f} ℃")
        for pump_id, pump in state.cooling_pumps.items():
            lines.append(f"  {pump.cfg.name}: {pump.state.value}")
        lines.append("")

        lines.append(f"【告警状态】")
        if state.level1_alarms:
            lines.append(f"  当前一级告警: {', '.join(state.level1_alarms)}")
        else:
            lines.append(f"  当前一级告警: 无")
        if state.level2_alarms:
            lines.append(f"  当前二级告警: {', '.join(state.level2_alarms)}")
        else:
            lines.append(f"  当前二级告警: 无")
        if state.level3_alarms:
            lines.append(f"  当前三级告警: {', '.join(state.level3_alarms)}")
        else:
            lines.append(f"  当前三级告警: 无")
        if state.esd_active:
            lines.append(f"  ESD复位码: {state.esd_reset_code}")
        lines.append("")

        lines.append("=" * 70)
        lines.append("                  报告结束")
        lines.append("=" * 70)

        return "\n".join(lines)

    def save_report(self, state: PlantState, recorder: Recorder, filename: str = "simulation_report.txt") -> None:
        report = self.generate_report(state, recorder)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report)
