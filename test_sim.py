#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速测试脚本 - 验证模拟器基本功能"""

import sys
sys.path.insert(0, '.')

from config import load_config
from simulator import Simulator
from cli import CLIParser


def test_config():
    print("=== 测试配置加载 ===")
    try:
        cfg = load_config("config.toml")
        print(f"✓ 配置加载成功")
        print(f"  电解槽数量: {len(cfg.electrolyzers)}")
        print(f"  储罐数量: {len(cfg.tanks)}")
        print(f"  纯化器数量: {len(cfg.purifiers)}")
        print(f"  冷却水泵数量: {cfg.cooling_system.pump_count}")
        print(f"  整流器数量: {len(cfg.rectifiers)}")
        return cfg
    except Exception as e:
        print(f"✗ 配置加载失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_simulator_init(cfg):
    print("\n=== 测试模拟器初始化 ===")
    try:
        sim = Simulator(cfg)
        sim.initialize()
        print(f"✓ 模拟器初始化成功")
        print(f"  当前步数: {sim.state.step}")
        print(f"  目标产量: {sim.state.target_demand} Nm³/h")
        print(f"  电解槽状态:")
        for cid, cell in sim.state.electrolyzers.items():
            print(f"    {cid}: {cell.state.value}")
        print(f"  储罐压力:")
        for tid, tank in sim.state.tanks.items():
            print(f"    {tid}: {tank.pressure} MPa")
        return sim
    except Exception as e:
        print(f"✗ 模拟器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_run_steps(sim, steps=30):
    print(f"\n=== 测试运行 {steps} 步 ===")
    try:
        for i in range(steps):
            sim.step()
        print(f"✓ 运行 {steps} 步成功")
        print(f"  当前步数: {sim.state.step}")
        print(f"  累计产氢: {sim.state.total_h2_produced:.4f} Nm³")
        print(f"  累计能耗: {sim.state.total_energy_kwh:.4f} kWh")
        print(f"  电解槽状态:")
        for cid, cell in sim.state.electrolyzers.items():
            print(f"    {cid}: state={cell.state.value}, load={cell.load_ratio*100:.1f}%, "
                  f"h2={cell.h2_output:.1f} Nm³/h, temp={cell.electrolyte_temp:.1f}℃, "
                  f"run_time={cell.run_time_total}min")
        print(f"  储罐状态:")
        for tid, tank in sim.state.tanks.items():
            print(f"    {tid}: pressure={tank.pressure:.2f} MPa, "
                  f"fill_rate={tank.fill_rate:.1f} Nm³/h, "
                  f"filling={tank.is_filling}, relieving={tank.is_relieving}")
    except Exception as e:
        print(f"✗ 运行失败: {e}")
        import traceback
        traceback.print_exc()


def test_scheduler(sim):
    print("\n=== 测试调度逻辑 ===")
    try:
        sim.set_demand(1200)
        print(f"  设置目标产量: 1200 Nm³/h")
        print(f"  调度计划:")
        for item in sim.current_schedule:
            print(f"    - {item.get('description', item.get('action'))}")
    except Exception as e:
        print(f"✗ 调度测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_interlock(sim):
    print("\n=== 测试安全联锁 ===")
    try:
        sim.inject_h2_leak(0.015)
        print(f"  注入氢气泄漏: 1.5% vol (一级报警阈值: 1%)")
        sim.step()
        print(f"  一级告警: {sim.state.level1_alarms}")
        print(f"  通风状态: {sim.state.ventilation_active}")

        sim.inject_h2_leak(0.025)
        print(f"  注入氢气泄漏: 2.5% vol (二级报警阈值: 2%)")
        sim.step()
        print(f"  二级告警: {sim.state.level2_alarms}")

        sim.inject_h2_leak(0)
        for i in range(10):
            sim.step()
        print(f"  通风10步后浓度: {sim.state.h2_concentration*100:.4f}% vol")
        print(f"  一级告警: {sim.state.level1_alarms}")

    except Exception as e:
        print(f"✗ 联锁测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_recorder(sim):
    print("\n=== 测试数据记录 ===")
    try:
        print(f"  历史记录条数: {len(sim.recorder.history)}")
        if sim.recorder.history:
            last = sim.recorder.history[-1]
            print(f"  最后一条: step={last['step']}, h2_output={last['total_h2_output']:.1f}")
    except Exception as e:
        print(f"✗ 记录测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_cli():
    print("\n=== 测试命令解析 ===")
    try:
        cli = CLIParser()
        test_commands = [
            "help",
            "status",
            "demand 1200",
            "set h2_leak 2%",
            "set tank1_pressure 39",
            "set cooling_pump1 off",
            "fire_alarm",
            "reset cell1",
            "esd_reset 1234",
            "history 10",
            "step 5",
            "quit",
        ]
        for cmd_str in test_commands:
            try:
                cmd = cli.parse(cmd_str)
                print(f"  ✓ {cmd_str} -> {cmd.command}, args={cmd.args}")
            except ValueError as e:
                print(f"  ? {cmd_str} -> {e}")
        print(f"✓ 命令解析测试完成")
    except Exception as e:
        print(f"✗ CLI测试失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("工业制氢站模拟器 - 快速测试")
    print("=" * 50)

    cfg = test_config()
    if not cfg:
        return

    sim = test_simulator_init(cfg)
    if not sim:
        return

    test_run_steps(sim, 30)
    test_scheduler(sim)
    test_interlock(sim)
    test_recorder(sim)
    test_cli()

    print("\n" + "=" * 50)
    print("测试完成!")


if __name__ == "__main__":
    main()
