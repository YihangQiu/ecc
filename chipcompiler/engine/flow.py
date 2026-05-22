#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import time
import logging
import traceback
import signal
from multiprocessing import Process
from threading import Thread

from chipcompiler.data import Workspace, WorkspaceStep, StateEnum, StepEnum, log_flow
from chipcompiler.engine import EngineDB
from chipcompiler.utility import track_process_memory
from chipcompiler.utility.log import redirect_stdio_to_file

logger = logging.getLogger(__name__)


def _read_process_cpu_jiffies(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        fields = open(f"/proc/{pid}/stat", encoding="utf-8").read().split()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    if len(fields) <= 14:
        return None
    try:
        return int(fields[13]) + int(fields[14])
    except ValueError:
        return None


def _path_mtime_ns(path: str) -> int | None:
    if not path:
        return None
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _terminate_process_tree(process: Process, step_tag: str, reason: str, workspace: Workspace) -> None:
    workspace.logger.error("[%s] %s terminating pid=%s", reason, step_tag, process.pid)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    process.join(timeout=10.0)
    if process.is_alive():
        workspace.logger.error("[%s] %s still alive; killing pid=%s", reason, step_tag, process.pid)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        process.join(timeout=5.0)

def _run_step_in_subprocess(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    """
    Step subprocess entry point: redirect stdio to log file if configured,
    then execute the EDA tool step.
    """
    # Redirect stdout/stderr to the step's own log file.
    log_file = workspace_step.log.get("file", "")
    if log_file:
        log_file = os.path.abspath(log_file)
        try:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            redirect_stdio_to_file(log_file)
        except Exception:
            traceback.print_exc()

    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    workspace.logger.info(f"[STEP] {step_tag} pid={os.getpid()} started")

    try:
        from chipcompiler.tools import run_step as run_tool_step
        result = run_tool_step(workspace=workspace, step=workspace_step)
        workspace.logger.info(f"[STEP] {step_tag} finished result={result}")
    except Exception:
        workspace.logger.error(f"[STEP] {step_tag} failed with exception")
        traceback.print_exc()


def _run_step_process_entry(step_runner, workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    try:
        os.setsid()
    except OSError:
        traceback.print_exc()
    step_runner(workspace, workspace_step)


def _run_step_inline(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    """
    Execute a step in the current process so pdb/debugpy can attach normally.
    """
    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    workspace.logger.info(f"[STEP] {step_tag} started inline pid={os.getpid()}")

    try:
        from chipcompiler.tools import run_step as run_tool_step
        result = run_tool_step(workspace=workspace, step=workspace_step)
        workspace.logger.info(f"[STEP] {step_tag} finished inline result={result}")
    except Exception:
        workspace.logger.error(f"[STEP] {step_tag} failed with exception")
        traceback.print_exc()


class EngineFlow:
    def __init__(self, workspace : Workspace):
        self.workspace = workspace
        self.workspace_steps = []
        self.db = None # db engine for this flow
        
        if self.workspace is not None:
            self.load()
    
    def build_default_steps(self):
        # Flow step sequences
        steps = []

        steps.append(self.init_flow_step(StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.PLACEMENT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.CTS, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_DRV, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_HOLD, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.LEGALIZATION, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.ROUTING, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FILLER, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.GDS, "klayout", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.SIGNOFF, "ecc", StateEnum.Unstart))
        
        self.workspace.flow.data = {"steps" : steps}
        
        self.save()
    
    def has_init(self):
        return True if self.workspace is not None and len(self.workspace.flow.data.get("steps", [])) > 0 else False
    
    def init_flow_step(self,
                  step : StepEnum | str,
                  tool : str,
                  state : str | StateEnum):
        step_value = step.value if isinstance(step, StepEnum) else step
        state_value = state.value if isinstance(state, StateEnum) else state
        return {
            "name" : step_value, # step name
            "tool" : tool, # eda tool name
            "state" : state_value, # step state
            "runtime" : "", # step run time
            "peak memory (mb)" : 0, # step peak memory
            "info" : {} # step additional infomation
        }
        
    def add_step(self,
                 step : StepEnum | str,
                 tool : str,
                 state : str | StateEnum):
        steps = self.workspace.flow.data.get("steps", [])
        steps.append(self.init_flow_step(step, tool, state))
        
        self.workspace.flow.data = {"steps" : steps}
        
        self.save()
    
    def load(self) -> bool:
        """
        load flow config json from workspace
        """
        from chipcompiler.utility import json_read
        self.workspace.flow.data = json_read(self.workspace.flow.path)
        if len(self.workspace.flow.data.get("steps", [])) <= 0:
            return False

        return True
        
    def save(self) -> bool:
        """
        save flow to workspace json
        """
        from chipcompiler.utility import json_write
        return json_write(self.workspace.flow.path, 
                          self.workspace.flow.data)
        
    def get_step(self,
                 name : str,
                 tool : str):
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                return step
        
        return None
    
    def get_workspace_step(self,
                           name : str) -> WorkspaceStep | None:
        for workspace_step in self.workspace_steps:
            if workspace_step.name == name:
                return workspace_step
        
        return None
    
    def check_state(self,
                   name : str,
                   tool : str,
                   state : str | StateEnum):
        """
        return True if step state has been set
        """
        step = self.get_step(name, tool)
        state_value = state.value if isinstance(state, StateEnum) else state
        if step is not None \
            and step.get("state") == state_value:
            return True
            
        return False
        
    def set_state(self, 
                 name : str,
                 tool : str,
                 state : str | StateEnum,
                 runtime : str=None,
                 peak_memory : float=None,
                 **info) -> bool:
        state_value = state.value if isinstance(state, StateEnum) else state
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                step["state"] = state_value
                if runtime is not None:
                    step["runtime"] = runtime
                if peak_memory is not None:
                    step["peak memory (mb)"] = peak_memory
                for key, value in info.items():
                    if value is not None:
                        step[key] = value

                self.save()
                return True
            
        return False
    
    def clear_states(self):
        from chipcompiler.data import StateEnum
        for step in self.workspace.flow.data.get("steps", []):
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0
            
        self.save()
        
    def is_flow_success(self):
        """
        check all steps success
        """
        from chipcompiler.data import StateEnum
        for step in self.workspace.flow.data.get("steps", []):
            if(step["state"] != StateEnum.Success.value):
                return False
            
        return True
    
    def check_step_result(self,
                          workspace_step : WorkspaceStep):
        """
        check step output exist
        """
        import os
        success = False

        route_completion_mode = str(
            self.workspace.parameters.data.get("route_completion_mode", "full_route")
            or "full_route"
        )
        if (
            workspace_step.name == StepEnum.ROUTING.value
            and route_completion_mode == "space_router_label"
        ):
            label_path = os.path.join(
                workspace_step.data.get(StepEnum.ROUTING.value, ""),
                "space_router",
                "route_native_demand_capacity_final.jsonl",
            )
            return os.path.exists(label_path) and os.path.getsize(label_path) > 0

        match workspace_step.name:
            case StepEnum.SYNTHESIS.value:
                if os.path.exists(workspace_step.output.get("verilog", "")):
                    success = True
            case StepEnum.HARDEN.value:
                if os.path.exists(workspace_step.output.get("lef", "")) and \
                    os.path.exists(workspace_step.output.get("lib", "")):
                    success = True
            case StepEnum.RCX.value:
                for spef in workspace_step.output.get("spef", []):
                    if not os.path.exists(spef):
                        break
                success = True
            case default:
                if os.path.exists(workspace_step.output.get("def", "")) and \
                    os.path.exists(workspace_step.output.get("verilog", "")) and \
                        os.path.exists(workspace_step.output.get("gds", "")):
                    success = True
        return success

    def create_step_workspaces(self):
        """
        create all step workspaces
        """
        pre_step = None
        for step in self.workspace.flow.data.get("steps", []):
            if pre_step is None:
                # use the origin def and verilog in workspace for the first step.
                input_def = self.workspace.design.origin_def
                input_verilog = self.workspace.design.origin_verilog
                input_db = None
            else:
                # use the output def and verilog from last step.
                input_def = pre_step.output.get("def", "")
                input_verilog = pre_step.output.get("verilog", "")
                input_db = pre_step.output.get("db", "")

            from chipcompiler.tools import create_step, run_step
            # create workspace step
            eda_step = create_step(workspace=self.workspace,
                                   step=step["name"],
                                   eda=step["tool"],
                                   input_def=input_def,
                                   input_verilog=input_verilog,
                                   input_db=input_db)
            # save workspace step
            if eda_step is not None:
                self.workspace_steps.append(eda_step)
                pre_step = eda_step
            else:
                # error create step, TBD
                pass
            
    def init_db_engine(self) -> bool:
        if len(self.workspace_steps) <= 0:
            return False
        
        if self.db is not None:
            return True
        
        # init engine step by last workpsace step data if all step run success
        workspace_step = self.workspace_steps[-1]
        for ws_step in self.workspace_steps:
            if not self.check_state(name=ws_step.name,
                                    tool=ws_step.tool,
                                    state=StateEnum.Success):
                # use the first unsuccess step to setup db engine
                workspace_step = ws_step
                                
        engine = EngineDB(workspace=self.workspace)
        if engine.create_db_engine(step=workspace_step):
            self.db = engine
            return True
        else:
            return False
        
    
    def run_steps(self, rerun=False) -> bool:
        """
        run all flow steps
        """
        
        self.workspace.home.reset() # reset home data before run steps
        
        for workspace_step in self.workspace_steps: 
            self.workspace.logger.log_section(f"{workspace_step.tool} - begin step - {workspace_step.name}")
            
            state = self.run_step(workspace_step, rerun)
            
            log_flow(workspace=self.workspace)
            self.workspace.logger.log_section(f"{workspace_step.tool} - end step - {workspace_step.name}")
            
            match(state):
                case StateEnum.Success:
                    continue
                case StateEnum.Invalid:
                    return False
                case StateEnum.Unstart:
                    return False
                case StateEnum.Imcomplete:
                    return False
                case StateEnum.Pending:
                    return False
                case StateEnum.Ongoing:
                    return False
        
        return True
            
    def run_step(self,
                 workspace_step : WorkspaceStep | str,
                 rerun : bool = False,
                 timeout_seconds : float | None = None,
                 stale_seconds : float | None = None) -> StateEnum:
        """
        run single step
        """
        if timeout_seconds is not None:
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be positive")
        if stale_seconds is not None:
            stale_seconds = float(stale_seconds)
            if stale_seconds <= 0:
                raise ValueError("stale_seconds must be positive")
        if isinstance(workspace_step, str):
            workspace_step = self.get_workspace_step(workspace_step)
        if workspace_step is None:
            return StateEnum.Invalid
            
        step_tag = f"{workspace_step.name}({workspace_step.tool})"

        if not rerun and self.check_state(name=workspace_step.name,
                            tool=workspace_step.tool,
                            state=StateEnum.Success):
            self.workspace.logger.info("[SKIP] %s already succeeded", step_tag)
            return StateEnum.Success

        # set state ongoing
        start_time = time.time()
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=StateEnum.Ongoing)

        # run step in a subprocess
        p = Process(target=_run_step_process_entry,
                    args=(_run_step_in_subprocess, self.workspace, workspace_step))
        p.start()
        step_log_file = workspace_step.log.get("file", "")
        logger.info("[DISPATCH] %s pid=%s log=%s", step_tag, p.pid,
                    os.path.abspath(step_log_file) if step_log_file else "N/A")

        # track peak memory in a background thread
        peak_memory_result = [0]
        def _track_memory():
            peak_memory_result[0] = track_process_memory(p.pid)
        tracker = Thread(target=_track_memory, daemon=True)
        tracker.start()

        timed_out = False
        stale_timed_out = False
        last_progress_time = time.time()
        last_cpu_jiffies = _read_process_cpu_jiffies(p.pid)
        last_log_mtime_ns = _path_mtime_ns(step_log_file)
        while p.is_alive():
            elapsed = time.time() - start_time
            join_timeout = 1.0
            if timeout_seconds is not None:
                join_timeout = max(0.0, min(join_timeout, timeout_seconds - elapsed))
                if join_timeout <= 0:
                    timed_out = True
                    break
            p.join(timeout=join_timeout)
            if not p.is_alive():
                break
            now = time.time()
            cpu_jiffies = _read_process_cpu_jiffies(p.pid)
            log_mtime_ns = _path_mtime_ns(step_log_file)
            if (
                (cpu_jiffies is not None and cpu_jiffies != last_cpu_jiffies)
                or (log_mtime_ns is not None and log_mtime_ns != last_log_mtime_ns)
            ):
                last_progress_time = now
                last_cpu_jiffies = cpu_jiffies
                last_log_mtime_ns = log_mtime_ns
            if stale_seconds is not None and now - last_progress_time >= stale_seconds:
                stale_timed_out = True
                break
        if timed_out and p.is_alive():
            _terminate_process_tree(p, step_tag, "TIMEOUT", self.workspace)
        elif stale_timed_out and p.is_alive():
            _terminate_process_tree(p, step_tag, "STALE", self.workspace)
        tracker.join(timeout=1.0)
        
        # compute metrics
        peak_memory_mb = 0
        elapsed = time.time() - start_time
        runtime = f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}"

        # determine and save state
        state = (
            StateEnum.Success
            if not timed_out and not stale_timed_out and self.check_step_result(workspace_step=workspace_step)
            else StateEnum.Imcomplete
        )
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=state,
                       runtime=runtime,
                       peak_memory=peak_memory_mb,
                       runtime_seconds=elapsed,
                       timeout_seconds=timeout_seconds if timed_out else None,
                       timed_out=timed_out if timed_out else None,
                       stale_seconds=stale_seconds if stale_timed_out else None,
                       stale_timed_out=stale_timed_out if stale_timed_out else None)
        self.workspace.logger.info("[RESULT] %s state=%s runtime=%s mem=%sMB exitcode=%s timed_out=%s stale_timed_out=%s",
                    step_tag, state.value, runtime, peak_memory_mb, p.exitcode, timed_out, stale_timed_out)

        # save layout snapshot on success when the step produced a full layout.
        route_completion_mode = str(
            self.workspace.parameters.data.get("route_completion_mode", "full_route")
            or "full_route"
        )
        space_router_only = (
            workspace_step.name == StepEnum.ROUTING.value
            and route_completion_mode == "space_router_label"
        )
        if state == StateEnum.Success and not space_router_only:
            from chipcompiler.tools import save_layout_image
            save_layout_image(workspace=self.workspace, step=workspace_step)

        return state
