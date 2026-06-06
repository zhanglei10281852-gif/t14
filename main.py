#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工业制氢站产能调度与安全联锁逻辑模拟器
"""

import sys
import logging
import threading
import time
from pathlib import Path

from config import load_config, PlantConfig
from simulator import Simulator
from cli import CLIParser


LOGO = r"""
  _    _           ____       _   _                 _ 
 | |  | |         |  _ \     | | (_)               | |
 | |__| |_   _    | |_) | ___| |_ _ _ __ ___   __ _| |
 |  __  | | | |   |  _ < / _ \ __| | '_ ` _ \ / _` | |
 | |  | | |_| |   | |_) |  __/ |_| | | | | | | (_| | |
 |_|  |_|\__, |   |____/ \___|\__|_|_| |_| |_|\__, |_|
          __/ |                                __/ |  
         |___/                                |___/   
        产能调度与安全联锁逻辑模拟器 v1.0
"""


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_status_rich(sim: Simulator) -> None:
    """使用rich库打印美化的状态表格"""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        console = Console()
        state = sim.state

        header_text = Text(f"制氢站运行状态 - 第 {state.step} 步", style="bold cyan")
        console.print(Panel(header_text, border_style="cyan"))

        info_table = Table(show_header=False, box=box.SIMPLE, expand=True)
        info_table.add_column("项目", style="bold", width=15)
        info_table.add_column("数值", style="green")

        total_h2 = sum(c.h2_output for c in state.electrolyzers.values())
        info_table.add_row("目标产量", f"{state.target_demand:.1f} Nm³/h")
        info_table.add_row("实际总产氢", f"{total_h2:.1f} Nm³/h")
        info_table.add_row("氢气浓度", f"{state.h2_concentration*100:.3f}% vol")
        info_table.add_row("冷却水温度", f"{state.cooling_water_temp:.1f} ℃")
        info_table.add_row("累计产氢", f"{state.total_h2_produced:.2f} Nm³")
        info_table.add_row("累计能耗", f"{state.total_energy_kwh:.2f} kWh")

        console.print(info_table)

        alarm_lines = []
        if state.esd_active:
            alarm_lines.append(f"[bold red]*** ESD紧急停车激活! 复位码: {state.esd_reset_code} ***")
        if state.fire_alarm_active:
            alarm_lines.append("[bold red]*** 火灾报警触发! ***")
        if state.level3_alarms:
            alarm_lines.append(f"[red]三级告警: {', '.join(state.level3_alarms)}")
        if state.level2_alarms:
            alarm_lines.append(f"[yellow]二级告警: {', '.join(state.level2_alarms)}")
        if state.level1_alarms:
            alarm_lines.append(f"[green]一级告警: {', '.join(state.level1_alarms)}")
        if state.ventilation_active:
            alarm_lines.append("[blue]强制通风系统运行中")

        if alarm_lines:
            console.print(Panel("\n".join(alarm_lines), title="告警状态", border_style="red"))

        cell_table = Table(title="电解槽状态", box=box.ROUNDED, expand=True)
        cell_table.add_column("设备ID", style="cyan", no_wrap=True)
        cell_table.add_column("名称", style="bold")
        cell_table.add_column("状态", justify="center")
        cell_table.add_column("负荷", justify="right")
        cell_table.add_column("产氢 (Nm³/h)", justify="right")
        cell_table.add_column("电解液温度", justify="right")
        cell_table.add_column("运行时间", justify="right")

        state_colors = {
            "stopped": "dim",
            "n2_purge": "yellow",
            "warmup": "blue",
            "running": "green",
            "load_reducing": "yellow",
            "emergency_stop": "red",
            "fault": "red bold",
        }

        for cid, cell in state.electrolyzers.items():
            state_str = cell.state.value
            color = state_colors.get(state_str, "white")
            cell_table.add_row(
                cid,
                cell.cfg.name,
                f"[{color}]{state_str}[/{color}]",
                f"{cell.load_ratio*100:.1f}%",
                f"{cell.h2_output:.1f}",
                f"{cell.electrolyte_temp:.1f} ℃",
                f"{cell.run_time_total} min",
            )

        console.print(cell_table)

        tank_table = Table(title="储罐状态", box=box.ROUNDED, expand=True)
        tank_table.add_column("罐号", style="cyan", no_wrap=True)
        tank_table.add_column("名称", style="bold")
        tank_table.add_column("压力 (MPa)", justify="right")
        tank_table.add_column("充装速率 (Nm³/h)", justify="right")
        tank_table.add_column("状态", justify="center")

        for tid, tank in state.tanks.items():
            pct = tank.pressure / tank.cfg.design_pressure * 100
            pressure_color = "green"
            if tank.pressure >= tank.cfg.trip_pressure:
                pressure_color = "red bold"
            elif tank.pressure >= tank.cfg.alarm_pressure:
                pressure_color = "yellow"

            status_parts = []
            if tank.is_filling:
                status_parts.append("[green]充装中[/green]")
            if tank.is_relieving:
                status_parts.append("[red]泄压中[/red]")
            status_str = " ".join(status_parts) if status_parts else "[dim]闲置[/dim]"

            tank_table.add_row(
                tid,
                tank.cfg.name,
                f"[{pressure_color}]{tank.pressure:.2f} / {tank.cfg.design_pressure:.0f} ({pct:.1f}%)[/{pressure_color}]",
                f"{tank.fill_rate:.1f}",
                status_str,
            )

        console.print(tank_table)

        pump_table = Table(title="冷却水泵", box=box.ROUNDED, expand=True)
        pump_table.add_column("泵号", style="cyan")
        pump_table.add_column("名称", style="bold")
        pump_table.add_column("状态", justify="center")
        pump_table.add_column("流量", justify="right")

        for pid, pump in state.cooling_pumps.items():
            color = "green" if pump.state.value == "active" else ("red" if pump.state.value == "fault" else "dim")
            pump_table.add_row(
                pid,
                pump.cfg.name,
                f"[{color}]{pump.state.value}[/{color}]",
                f"{pump.flow_rate:.2f}",
            )

        console.print(pump_table)

    except ImportError:
        print(sim.get_status_text())


class SimulationApp:
    def __init__(self, config_path: str = "config.toml"):
        self.config = load_config(config_path)
        self.sim = Simulator(self.config)
        self.cli = CLIParser()
        self.running = False
        self.auto_mode = False
        self.auto_thread = None
        self.auto_speed = 1.0

    def start(self) -> None:
        setup_logging(self.config.general.log_level)
        self.sim.initialize()

        print(LOGO)
        print("工业制氢站产能调度与安全联锁逻辑模拟器")
        print("输入 help 查看命令列表，输入 quit 退出")
        print("=" * 60)
        print()

        self._print_status()

        self.running = True
        self._command_loop()

    def _command_loop(self) -> None:
        while self.running:
            try:
                user_input = input("\n[模拟器] > ").strip()
                if not user_input:
                    continue

                try:
                    cmd = self.cli.parse(user_input)
                except ValueError as e:
                    print(f"[错误] {e}")
                    continue

                if cmd is None:
                    continue

                self._handle_command(cmd)

            except KeyboardInterrupt:
                print("\n检测到中断，正在退出...")
                self._shutdown()
                break
            except Exception as e:
                print(f"[错误] 命令执行失败: {e}")
                import traceback
                traceback.print_exc()

    def _handle_command(self, cmd) -> None:
        if cmd.command == "help":
            print(self.cli.get_help_text())

        elif cmd.command == "status":
            self._print_status()

        elif cmd.command == "demand":
            value = cmd.args["value"]
            self.sim.set_demand(value)
            print(f"[调度] 目标产量已设置为 {value} Nm³/h")

        elif cmd.command == "set_h2_leak":
            conc = cmd.args["concentration"]
            self.sim.inject_h2_leak(conc)
            print(f"[事件] 注入氢气泄漏事件: {conc*100:.2f}% vol")

        elif cmd.command == "set_tank_pressure":
            tank_id = cmd.args["tank_id"]
            pressure = cmd.args["pressure"]
            self.sim.set_tank_pressure(tank_id, pressure)
            print(f"[事件] {tank_id} 压力设为 {pressure} MPa")

        elif cmd.command == "set_pump":
            pump_id = cmd.args["pump_id"]
            state_str = cmd.args["state"]
            self.sim.set_pump_state(pump_id, state_str)
            print(f"[事件] {pump_id} 设置为 {state_str}")

        elif cmd.command == "fire_alarm":
            self.sim.trigger_fire_alarm()
            print("[紧急] 火灾报警已触发!")

        elif cmd.command == "reset":
            device_id = cmd.args["device_id"]
            result = self.sim.reset_device(device_id)
            if result:
                print(f"[复位] {device_id} 复位成功")
            else:
                print(f"[复位] {device_id} 复位失败，请检查设备状态")

        elif cmd.command == "esd_reset":
            code = cmd.args["code"]
            result = self.sim.reset_esd(code)
            if result:
                print("[复位] ESD紧急停车已复位")
            else:
                print("[复位] ESD复位失败，确认码错误")

        elif cmd.command == "history":
            n = cmd.args.get("n", 10)
            print(self.sim.get_history_text(n))

        elif cmd.command == "step":
            n = cmd.args["n"]
            print(f"[模拟] 快进 {n} 步...")
            self.sim.run_n_steps(n)
            self._print_status()

        elif cmd.command == "auto":
            enabled = cmd.args.get("enabled", True)
            if enabled:
                self._start_auto_mode()
            else:
                self._stop_auto_mode()

        elif cmd.command == "schedule":
            self._print_schedule()

        elif cmd.command == "alarms":
            self._print_alarms()

        elif cmd.command == "report":
            print(self.sim.get_report())

        elif cmd.command == "quit":
            self._shutdown()

        else:
            print(f"[未知命令] {cmd.command}")

    def _print_status(self) -> None:
        print_status_rich(self.sim)

    def _print_schedule(self) -> None:
        print("当前调度计划:")
        if not self.sim.current_schedule:
            print("  (无调度动作)")
        for item in self.sim.current_schedule:
            print(f"  - {item.get('description', item.get('action'))}")

    def _print_alarms(self) -> None:
        state = self.sim.state
        print("当前告警状态:")
        print(f"  三级告警: {state.level3_alarms if state.level3_alarms else '无'}")
        print(f"  二级告警: {state.level2_alarms if state.level2_alarms else '无'}")
        print(f"  一级告警: {state.level1_alarms if state.level1_alarms else '无'}")
        if state.esd_active:
            print(f"  ESD状态: 激活 (复位码: {state.esd_reset_code})")
        else:
            print(f"  ESD状态: 未激活")

    def _start_auto_mode(self) -> None:
        if self.auto_mode:
            print("[自动] 自动模式已在运行中")
            return
        self.auto_mode = True
        self.auto_thread = threading.Thread(target=self._auto_run, daemon=True)
        self.auto_thread.start()
        print("[自动] 自动步进模式已开启")

    def _stop_auto_mode(self) -> None:
        if not self.auto_mode:
            print("[自动] 自动模式未运行")
            return
        self.auto_mode = False
        print("[自动] 自动步进模式已停止")

    def _auto_run(self) -> None:
        while self.auto_mode and self.running:
            self.sim.step()
            self._print_status()
            time.sleep(self.auto_speed)

    def _shutdown(self) -> None:
        print("\n[系统] 正在关闭模拟器...")
        self.running = False
        self.auto_mode = False
        if self.auto_thread and self.auto_thread.is_alive():
            self.auto_thread.join(timeout=2)

        print("\n" + self.sim.get_report())
        self.sim.save_report()
        print(f"[系统] 数据已保存到 {self.config.recorder.csv_file}")
        print(f"[系统] 报告已保存到 simulation_report.txt")
        print("[系统] 再见!")


def main() -> None:
    config_path = "config.toml"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    if not Path(config_path).exists():
        print(f"错误: 配置文件 {config_path} 不存在")
        sys.exit(1)

    try:
        app = SimulationApp(config_path)
        app.start()
    except Exception as e:
        print(f"程序启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
