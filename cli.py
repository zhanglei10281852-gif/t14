from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class CLICommand:
    command: str
    args: Dict[str, Any]
    raw: str


class CLIParser:
    def __init__(self):
        self.commands_info = {
            "help": "显示帮助信息",
            "status": "查看当前全状态",
            "demand <value>": "修改产氢需求量 (Nm³/h)",
            "set h2_leak <percent>": "模拟氢气泄漏 (百分比 1-4)",
            "set tank<int>_pressure <mpa>": "强设储罐压力 (MPa)",
            "set cooling_pump<int> off": "模拟水泵故障",
            "set cooling_pump<int> on": "启动备用泵",
            "fire_alarm": "模拟火灾报警",
            "reset <device_id>": "复位二级联锁设备",
            "esd_reset <code>": "复位ESD紧急停车",
            "history <n>": "查看最近n步历史",
            "step <n>": "快进n步",
            "auto <on|off>": "开启/关闭自动步进模式",
            "schedule": "查看当前调度计划",
            "alarms": "查看当前告警状态",
            "report": "生成当前统计报告",
            "quit": "退出模拟程序",
        }

    def parse(self, input_str: str) -> Optional[CLICommand]:
        input_str = input_str.strip()
        if not input_str:
            return None

        parts = input_str.split()
        if not parts:
            return None

        cmd = parts[0].lower()
        args = {}

        try:
            if cmd == "help":
                return CLICommand(command="help", args={}, raw=input_str)

            elif cmd == "status":
                return CLICommand(command="status", args={}, raw=input_str)

            elif cmd == "demand":
                if len(parts) < 2:
                    raise ValueError("缺少需求量参数")
                value = float(parts[1])
                if value < 0:
                    raise ValueError("需求量不能为负")
                args["value"] = value
                return CLICommand(command="demand", args=args, raw=input_str)

            elif cmd == "set":
                if len(parts) < 3:
                    raise ValueError("set命令格式错误，用法: set <target> <value>")
                target = parts[1].lower()
                value = parts[2].lower()

                if target == "h2_leak":
                    try:
                        pct = float(value.strip("%"))
                        args["concentration"] = pct / 100.0
                        return CLICommand(command="set_h2_leak", args=args, raw=input_str)
                    except ValueError:
                        raise ValueError("氢气浓度必须是数字")

                elif target.startswith("tank") and target.endswith("_pressure"):
                    try:
                        tank_num = int(target.replace("tank", "").replace("_pressure", ""))
                        pressure = float(value)
                        args["tank_id"] = f"tank{tank_num}"
                        args["pressure"] = pressure
                        return CLICommand(command="set_tank_pressure", args=args, raw=input_str)
                    except ValueError:
                        raise ValueError("储罐编号或压力值格式错误")

                elif target.startswith("cooling_pump"):
                    pump_id = target
                    if value == "off":
                        args["pump_id"] = pump_id
                        args["state"] = "fault"
                        return CLICommand(command="set_pump", args=args, raw=input_str)
                    elif value == "on":
                        args["pump_id"] = pump_id
                        args["state"] = "active"
                        return CLICommand(command="set_pump", args=args, raw=input_str)
                    else:
                        raise ValueError("水泵状态只能是 on 或 off")

                else:
                    raise ValueError(f"未知的set目标: {target}")

            elif cmd == "fire_alarm":
                return CLICommand(command="fire_alarm", args={}, raw=input_str)

            elif cmd == "reset":
                if len(parts) < 2:
                    raise ValueError("缺少设备ID")
                args["device_id"] = parts[1]
                return CLICommand(command="reset", args=args, raw=input_str)

            elif cmd == "esd_reset":
                if len(parts) < 2:
                    raise ValueError("缺少确认码")
                args["code"] = parts[1]
                return CLICommand(command="esd_reset", args=args, raw=input_str)

            elif cmd == "history":
                n = 10
                if len(parts) >= 2:
                    try:
                        n = int(parts[1])
                    except ValueError:
                        raise ValueError("步数必须是整数")
                args["n"] = n
                return CLICommand(command="history", args=args, raw=input_str)

            elif cmd == "step":
                if len(parts) < 2:
                    raise ValueError("缺少步数")
                try:
                    n = int(parts[1])
                except ValueError:
                    raise ValueError("步数必须是整数")
                args["n"] = n
                return CLICommand(command="step", args=args, raw=input_str)

            elif cmd == "auto":
                if len(parts) < 2:
                    args["enabled"] = True
                else:
                    args["enabled"] = parts[1].lower() in ("on", "true", "1", "yes")
                return CLICommand(command="auto", args=args, raw=input_str)

            elif cmd == "schedule":
                return CLICommand(command="schedule", args={}, raw=input_str)

            elif cmd == "alarms":
                return CLICommand(command="alarms", args={}, raw=input_str)

            elif cmd == "report":
                return CLICommand(command="report", args={}, raw=input_str)

            elif cmd in ("quit", "exit", "q"):
                return CLICommand(command="quit", args={}, raw=input_str)

            else:
                raise ValueError(f"未知命令: {cmd}，输入 help 查看帮助")

        except ValueError as e:
            raise e

    def get_help_text(self) -> str:
        lines = ["可用命令列表:", ""]
        for cmd, desc in self.commands_info.items():
            lines.append(f"  {cmd:<30} - {desc}")
        lines.append("")
        lines.append("示例:")
        lines.append("  demand 1200        # 设置目标产量为1200 Nm³/h")
        lines.append("  set h2_leak 2%     # 模拟氢气浓度达到2%")
        lines.append("  set tank1_pressure 39  # 设置1号罐压力为39MPa")
        lines.append("  fire_alarm         # 触发火灾报警")
        lines.append("  reset cell1        # 复位1号电解槽")
        lines.append("  step 5             # 快进5步")
        return "\n".join(lines)
