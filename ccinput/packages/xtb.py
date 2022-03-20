import os

from ccinput.constants import CalcType, ATOMIC_NUMBER, LOWERCASE_ATOMIC_SYMBOLS
from ccinput.utilities import get_solvent
from ccinput.exceptions import InvalidParameter


class XtbCalculation:

    EXECUTABLES = {
        CalcType.OPT: "xtb",
        CalcType.CONSTR_OPT: "xtb",
        CalcType.FREQ: "xtb",
        CalcType.SP: "xtb",
        CalcType.UVVIS_TDA: "stda",
        CalcType.OPTFREQ: "xtb",
        CalcType.CONF_SEARCH: "crest",
        CalcType.CONSTR_CONF_SEARCH: "crest",
    }

    def __init__(self, calc):
        self.calc = calc
        self.program = ""
        self.cmd_arguments = ""
        self.option_file = ""
        self.specifications = ""
        self.force_constant = 1.0

        self.handle_command()
        self.handle_specifications()

        if self.calc.type == CalcType.CONSTR_CONF_SEARCH:
            self.handle_constraints_crest()
        elif self.calc.type == CalcType.CONSTR_OPT:
            self.handle_constraints_scan()

        self.handle_parameters()

        self.create_command()

    def handle_parameters(self):
        if self.calc.parameters.solvent != "":
            try:
                solvent_keyword = get_solvent(
                    self.calc.parameters.solvent, self.calc.parameters.software
                )
            except KeyError:
                raise InvalidParameter("Invalid solvent")

            if self.calc.parameters.solvation_model == "gbsa":
                self.cmd_arguments += f"-g {solvent_keyword} "
            elif self.calc.parameters.solvation_model == "alpb":
                self.cmd_arguments += f"--alpb {solvent_keyword} "
            else:
                raise InvalidParameter(
                    "Invalid solvation method for xtb: {}".format(
                        self.calc.parameters.solvation_model
                    )
                )

        if self.calc.charge != 0:
            self.cmd_arguments += f"--chrg {self.calc.charge} "

        if self.calc.multiplicity != 1:
            self.cmd_arguments += f"--uhf {self.calc.multiplicity} "

    def handle_constraints_scan(self):
        if len(self.calc.constraints) == 0:
            return

        self.option_file += "$constrain\n"
        self.option_file += f"force constant={self.force_constant}\n"
        self.has_scan = False

        for cmd in self.calc.constraints:
            self.option_file += cmd.to_xtb()
            if cmd.scan:
                self.has_scan = True

        if self.has_scan:
            self.option_file += "$scan\n"
            for counter, cmd in enumerate(self.calc.constraints):
                if cmd.scan:
                    self.option_file += (
                        f"{counter+1}: {cmd.start_d}, {cmd.end_d}, {cmd.num_steps}\n"
                    )

    def compress_indices(self, arr):
        comp = []

        def add_to_str(curr):
            if len(curr) == 0:
                return ""
            elif len(curr) == 1:
                return f"{curr[0]}"
            else:
                return f"{curr[0]}-{curr[-1]}"

        _arr = sorted(set(arr))
        curr_atoms = []

        for a in _arr:
            if len(curr_atoms) == 0:
                curr_atoms.append(a)
            else:
                if a == curr_atoms[-1] + 1:
                    curr_atoms.append(a)
                else:
                    comp.append(add_to_str(curr_atoms))
                    curr_atoms = [a]

        comp.append(add_to_str(curr_atoms))
        return ",".join(comp)

    def handle_constraints_crest(self):
        num_atoms = len(self.calc.xyz.split("\n"))
        input_file_name = os.path.basename(self.calc.file)

        self.option_file += "$constrain\n"
        self.option_file += f"force constant={self.force_constant}\n"
        self.option_file += f"reference={input_file_name}\n"
        constr_atoms = []
        for cmd in self.calc.constraints:
            self.option_file += cmd.to_xtb()
            constr_atoms += cmd.ids

        self.option_file += f"atoms: {self.compress_indices(constr_atoms)}\n"

        mtd_atoms = list(range(1, num_atoms))
        for a in constr_atoms:
            if int(a) in mtd_atoms:
                mtd_atoms.remove(int(a))

        self.option_file += "$metadyn\n"
        self.option_file += f"atoms: {self.compress_indices(mtd_atoms)}\n"

    def handle_specifications(self):
        SPECIFICATIONS = {
            "general": {
                "acc": 1,
                "iterations": 1,
                "gfn2-xtb": 0,
                "gfn1-xtb": 0,
                "gfn0-xtb": 0,
                "gfn-ff": 0,
            },
            "Geometrical Optimisation": {
                "opt(crude)": 0,
                "opt(sloppy)": 0,
                "opt(loose)": 0,
                "opt(lax)": 0,
                "opt(normal)": 0,
                "opt(tight)": 0,
                "opt(vtight)": 0,
                "opt(extreme)": 0,
            },
            "Conformational Search": {
                "gfn2-xtb//gfn-ff": 0,
                "rthr": 1,
                "ewin": 1,
                "quick": 0,
                "squick": 0,
                "mquick": 0,
            },
        }

        accuracy = -1
        iterations = -1
        method = "gfn2-xtb"
        opt_level = "tight"
        rthr = 0.6
        ewin = 6
        cmd_arguments = ""

        ALLOWED = "qwertyuiopasdfghjklzxcvbnm-1234567890./= "
        clean_specs = "".join(
            [
                i
                for i in self.specifications
                + self.calc.parameters.specifications.lower()
                if i in ALLOWED
            ]
        )
        clean_specs = clean_specs.replace("=", " ").replace("  ", " ")

        specs = clean_specs.strip().split("--")

        for spec in specs:
            if spec.strip() == "":
                continue
            ss = spec.strip().split()
            if len(ss) == 1:
                if ss[0] in ["gfn2", "gfn1", "gfn0", "gfnff", "gfn2//gfnff"]:
                    if ss[0] == "gfn2//gfnff" and self.calc.type not in [
                        CalcType.CONF_SEARCH,
                        CalcType.CONSTR_CONF_SEARCH,
                    ]:
                        raise InvalidParameter(
                            f"Invalid method for calculation type: {ss[0]}"
                        )
                    if ss[0] in ["gfn2", "gfn1", "gfn0"]:
                        method = f"{ss[0][:-1]} {ss[0][-1]}"
                    else:
                        method = ss[0]
                elif ss[0] == "nci":
                    self.cmd_arguments += "--nci "
                elif ss[0] == "quick":
                    self.cmd_arguments += "--quick "
                elif ss[0] == "squick":
                    self.cmd_arguments += "--squick "
                elif ss[0] == "mquick":
                    self.cmd_arguments += "--mquick "
                else:
                    raise InvalidParameter("Invalid specification")
            elif len(ss) == 2:
                if ss[0] == "o" or ss[0] == "opt":
                    if ss[1] not in [
                        "crude",
                        "sloppy",
                        "loose",
                        "lax",
                        "normal",
                        "tight",
                        "vtight",
                        "extreme",
                    ]:
                        raise InvalidParameter("Invalid optimization specification")
                    opt_level = ss[1]
                elif ss[0] == "rthr":
                    if self.calc.type not in [
                        CalcType.CONF_SEARCH,
                        CalcType.CONSTR_CONF_SEARCH,
                    ]:
                        raise InvalidParameter(
                            "Invalid specification for calculation type: rthr"
                        )
                    rthr = ss[1]
                elif ss[0] == "ewin":
                    if self.calc.type not in [
                        CalcType.CONF_SEARCH,
                        CalcType.CONSTR_CONF_SEARCH,
                    ]:
                        raise InvalidParameter(
                            "Invalid specification for calculation type: ewin"
                        )
                    ewin = ss[1]
                elif ss[0] == "acc":
                    accuracy = float(ss[1])
                elif ss[0] == "iterations":
                    try:
                        iterations = int(ss[1])
                    except ValueError:
                        raise InvalidParameter(
                            "Invalid number of iterations: must be an integer"
                        )
                elif ss[0] == "forceconstant":
                    try:
                        self.force_constant = float(ss[1])
                    except ValueError:
                        raise InvalidParameter(
                            "Invalid force constant: must be a floating point value"
                        )
                elif ss[0] == "gfn":
                    if ss[1] not in ["0", "1", "2"]:
                        raise InvalidParameter("Invalid GFN version")
                    method = f"{ss[0]} {ss[1]}"
                else:
                    raise InvalidParameter(f"Unknown specification: {ss[0]}")
            else:
                raise InvalidParameter(f"Invalid specification: {ss}")

        if accuracy != -1:
            self.cmd_arguments += f"--acc {accuracy:.2f} "
        if iterations != -1:
            self.cmd_arguments += f"--iterations {iterations} "
        if method != "gfn2-xtb" and method != "gfn 2":
            self.cmd_arguments += f"--{method} "
        if opt_level != "normal":
            self.cmd_arguments = self.cmd_arguments.replace(
                "--opt ", f"--opt {opt_level} "
            )

        if self.calc.type in [CalcType.CONF_SEARCH, CalcType.CONSTR_CONF_SEARCH]:
            self.cmd_arguments += f"--rthr {rthr} --ewin {ewin} "

            self.cmd_arguments = self.cmd_arguments.replace(
                "--", "-"
            )  # Crest 2.10.2 does not read arguments with double dashes

    def handle_command(self):
        self.program = self.EXECUTABLES[self.calc.type]

        if self.calc.type == CalcType.OPT:
            self.specifications = "--opt tight "
            self.cmd_arguments += "--opt "
        elif self.calc.type == CalcType.OPTFREQ:
            self.specifications = (
                "--ohess tight "  # Not sure if the tightness will be parsed
            )
        # elif self.calc.type == "Conformational Search":
        #    self.specifications = "--rthr 0.6 --ewin 6 "
        elif self.calc.type == CalcType.CONSTR_CONF_SEARCH:
            self.cmd_arguments += "-cinp input "
        elif self.calc.type == CalcType.CONSTR_OPT:
            self.cmd_arguments += "--opt --input input "
        elif self.calc.type == CalcType.FREQ:
            self.cmd_arguments += "--hess "

    def create_command(self):
        input_file_name = os.path.basename(self.calc.file)
        self.command = f"{self.program} {input_file_name} {self.cmd_arguments}"