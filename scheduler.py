from typing import List, Dict, Tuple, Optional
from plant_model import PlantState, Electrolyzer, CellState
from config import PlantConfig, SchedulerConfig


class Scheduler:
    def __init__(self, config: PlantConfig):
        self.config = config
        self.sched_cfg = config.scheduler
        self.schedule_plan: List[dict] = []

    def generate_schedule(self, state: PlantState, target_demand: float) -> List[dict]:
        """生成调度计划，返回未来几步的操作列表"""
        plan = []
        cells = list(state.electrolyzers.values())
        running_cells = [c for c in cells if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING)]
        starting_cells = [c for c in cells if c.state in (CellState.N2_PURGE, CellState.WARMUP)]
        stopped_cells = [c for c in cells if c.state == CellState.STOPPED]

        current_output = sum(c.h2_output for c in running_cells)
        starting_capacity = sum(c.cfg.rated_h2_output * c.load_limit_ratio for c in starting_cells)

        if target_demand <= 0:
            for cell in running_cells:
                plan.append({
                    "step_offset": 0,
                    "action": "stop",
                    "cell_id": cell.cfg.id,
                    "description": f"停止{cell.cfg.name}",
                })
            return plan

        needed_extra = target_demand - current_output

        if needed_extra > 0 and len(starting_cells) == 0:
            available_capacity = 0
            sorted_stopped = sorted(stopped_cells, key=lambda c: c.run_time_total)
            for cell in sorted_stopped:
                cell_cap = cell.cfg.rated_h2_output * cell.load_limit_ratio
                if current_output + available_capacity < target_demand:
                    available_capacity += cell_cap
                    plan.append({
                        "step_offset": 0,
                        "action": "start_purge",
                        "cell_id": cell.cfg.id,
                        "description": f"启动{cell.cfg.name}氮气置换",
                    })
                else:
                    break

        active_cells = running_cells + starting_cells
        if len(active_cells) > 0:
            num_active = len(active_cells)
            per_cell_target = target_demand / num_active
            for cell in running_cells:
                target_ratio = per_cell_target / cell.cfg.rated_h2_output
                target_ratio = max(cell.min_load_ratio, min(target_ratio, cell.max_load_ratio))
                plan.append({
                    "step_offset": 0,
                    "action": "set_load",
                    "cell_id": cell.cfg.id,
                    "target_ratio": target_ratio,
                    "description": f"设置{cell.cfg.name}负荷为{target_ratio*100:.1f}%",
                })

        if needed_extra < -50 and len(running_cells) > 1:
            min_output = running_cells[0].cfg.rated_h2_output * running_cells[0].cfg.min_load_ratio
            reduced_output = current_output - min_output
            if reduced_output >= target_demand:
                cell_to_stop = max(running_cells, key=lambda c: c.run_time_total)
                plan.append({
                    "step_offset": 0,
                    "action": "stop",
                    "cell_id": cell_to_stop.cfg.id,
                    "description": f"停止{cell_to_stop.cfg.name}降载",
                })
                remaining = [c for c in running_cells if c.cfg.id != cell_to_stop.cfg.id]
                if remaining:
                    new_per_cell = target_demand / len(remaining)
                    for cell in remaining:
                        target_ratio = new_per_cell / cell.cfg.rated_h2_output
                        target_ratio = max(cell.min_load_ratio, min(target_ratio, cell.max_load_ratio))
                        plan.append({
                            "step_offset": 0,
                            "action": "set_load",
                            "cell_id": cell.cfg.id,
                            "target_ratio": target_ratio,
                            "description": f"调整{cell.cfg.name}负荷为{target_ratio*100:.1f}%",
                        })

        return plan

    def apply_command(self, state: PlantState, command: dict) -> bool:
        action = command.get("action")
        cell_id = command.get("cell_id")
        if not cell_id or cell_id not in state.electrolyzers:
            return False
        cell = state.electrolyzers[cell_id]

        if action == "start_purge":
            return cell.start_purge()
        elif action == "start_warmup":
            return cell.start_warmup()
        elif action == "start_running":
            return cell.start_running()
        elif action == "set_load":
            target_ratio = command.get("target_ratio", 0.0)
            target_ratio = max(cell.min_load_ratio, min(target_ratio, cell.max_load_ratio))
            cell.target_load_ratio = target_ratio
            return True
        elif action == "stop":
            cell.stop()
            return True
        elif action == "emergency_stop":
            cell.emergency_stop(command.get("reason", "scheduler"))
            return True
        elif action == "reset":
            return cell.reset_from_fault()
        return False

    def estimate_time_to_target(self, state: PlantState, target_demand: float) -> Tuple[int, float]:
        """预计多少步后达到目标产量"""
        cells = list(state.electrolyzers.values())
        running_cells = [c for c in cells if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING)]
        starting_cells = [c for c in cells if c.state in (CellState.N2_PURGE, CellState.WARMUP)]
        stopped_cells = [c for c in cells if c.state == CellState.STOPPED]

        current_output = sum(c.h2_output for c in running_cells)
        if current_output >= target_demand - 1:
            return 0, current_output

        ramp_rate_per_cell = cells[0].cfg.rated_h2_output * cells[0].cfg.ramp_rate_per_min if cells else 0
        steps = 0
        estimated_output = current_output

        if len(running_cells) > 0 and len(starting_cells) == 0 and len(stopped_cells) > 0:
            max_running = sum(c.cfg.rated_h2_output for c in running_cells)
            if max_running < target_demand:
                cell_to_start = min(stopped_cells, key=lambda c: c.run_time_total)
                startup_time = cell_to_start.cfg.n2_purge_time + cell_to_start.cfg.warmup_time
                return (startup_time + 10, cell_to_start.cfg.rated_h2_output * cell_to_start.min_load_ratio)

        if running_cells:
            target_per_cell = target_demand / (len(running_cells) + len(starting_cells))
            max_per_cell = max(c.h2_output for c in running_cells) if running_cells else 0
            ramp_needed = target_per_cell - max_per_cell
            if ramp_needed > 0 and ramp_rate_per_cell > 0:
                steps = int(ramp_needed / ramp_rate_per_cell) + 1

        return steps, target_demand


def manage_tank_filling(state: PlantState) -> float:
    """储罐充装管理，返回实际充装的总量（Nm³/h流量）"""
    total_h2 = sum(c.h2_output for c in state.electrolyzers.values() if c.state in (CellState.RUNNING, CellState.LOAD_REDUCING))
    purifier_capacity = sum(p.cfg.capacity for p in state.purifiers.values() if p.state.value == "active")
    available_h2 = min(total_h2, purifier_capacity)
    available_per_step = available_h2 / 60.0

    for tank in state.tanks.values():
        tank.reset_fill_state()

    remaining = available_per_step
    sorted_tanks = sorted(state.tanks.values(), key=lambda t: t.pressure)

    for tank in sorted_tanks:
        if remaining <= 0:
            break
        if tank.is_relieving or tank.pressure >= tank.cfg.high_pressure:
            continue
        filled = tank.fill(remaining)
        remaining -= filled

    state.total_h2_produced += available_per_step

    all_full = all(t.pressure >= t.cfg.high_pressure for t in state.tanks.values())
    if all_full:
        for cell in state.electrolyzers.values():
            if cell.state == CellState.RUNNING:
                cell.target_load_ratio = cell.min_load_ratio

    return available_h2
