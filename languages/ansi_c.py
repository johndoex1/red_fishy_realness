import re
import copy
import random
import string

from obfuser import Obfuser


class ObfuserAnsiC(Obfuser):
    def create_code(self):

        self.code_includes = []
        self.code_macros = []
        self.code_functions = []

        self.code_types = ["bool", "int", "float", "char", "char*"]
        self.code_types_dict = {"int": 0, "char": 1, "char*": 2}

        self.regex_function = "[\w\*\[\]]+\s\w+\\(([\w\*\[\]]+\s\w+(\s*),(\s*))*([\w\*\[\]]+\s\w+){0,1}\\)"
        self.regex_conditional = "^(if|else if|else)"
        self.regex_loop = "^(for|while|do)"

        # Walk the original code and break up
        # TODO: Replace this with regex replace
        self.code_clean = self.code_original.replace(";", ";\n").replace("{", "\n{\n").replace("}", "\n}\n").replace("\n\n", "\n").replace("\n\n", "\n").split("\n")

        while True:
            if self.code_clean[0].strip().startswith("#pragma") or self.code_clean[0].strip().startswith("#include"):
                self.obfuscated_prefix.append(self.code_clean[0])
                del self.code_clean[0]
            elif self.code_clean[0].strip() == "":
                del self.code_clean[0]
            else:
                break

        code_block = self.create_code_block(self.code_clean, {"name": "", "return": "", "args": []}, [],
                                            add_return=False, code_levels=3, in_func=False)

        self.fill_obfuscated_code(code_block["code"])
        self.obfuscated_code_string = self.fill_code_string(self.obfuscated_code, 0)

    def create_code_fake_globals(self):
        for i in range(len(self.code_types)):
            for j in range(random.randint(5,15)):
                g = self.create_random_variable(self.code_types_dict[i], "gvar")
                self.code_fake_globals.append(g)

    def create_code_block(self, real_code, current_signature, lv, add_return=False, code_levels=10, in_func=False):
        ret = {"code": [], "used_vars": []}

        # Track the local variables to make sure they get used up
        unused_locals = []

        old_local_vars = copy.copy(lv)

        # Generate local variables for the code block
        new_local_vars = []
        for i in range(len(self.code_types)):
            for j in range(random.randint(1, 2)):
                new_local_vars.append(self.create_random_variable(self.code_types[i], "lvar"))
        random.shuffle(new_local_vars)

        # Add them to the code block return
        for lv in new_local_vars:
            ret["code"].append(lv["line"])
            unused_locals.append(lv)

        local_vars = old_local_vars
        local_vars.extend(new_local_vars)

        # Keep creating code until there isn't any more real code to include
        # As real code is used, it will be removed from the list
        while True:
            r = self.config.choose_weighted()

            #print "%d %s" % (len(unused_locals), unused_locals[0]["type"])

            # If there's no real code left but we have unused local variables, focus what we create to use them
            if (not real_code) and unused_locals and in_func:
                unused_type = unused_locals[0]["type"]
                if unused_type in ["int", "float32", "bool", "[]int", "map[string]int"]:
                    r = "math"
                elif unused_type in ["byte", "string", "[]string", "map[string]string"]:
                    r = "string"

            # Force real code to be used immediately if it is the continuation of an if else block
            # Otherwise there can be code between if and else, causing syntax errors
            elif real_code and re.match("^(else if|else)", real_code[0]):
                r = "real"

            gen_code = {}

            # Handle functions
            if r == "function":
                if code_levels <= 0:
                    continue

                # Create the new function signature
                signature = {"name": "", "return": random.choice(self.code_types), "args": []}
                while (signature["name"] == "") or (signature["name"] in self.used_functions):
                    signature["name"] = "sub_%s" % self.random_lower_alphanum(random.randint(5, 32))
                self.used_functions.add(signature["name"])

                # Create random arguments for the function
                for arg_count in range(random.randint(1, 5)):
                    signature["args"].append(self.create_random_variable(random.choice(self.code_types), "avar"))

                # Create the function call
                return_var = self.pick_unused_variable(signature["return"], unused_locals, current_signature["args"]+local_vars)["name"]
                func_call = "%s = %s(" % (return_var, signature["name"])
                if return_var in unused_locals:
                    del unused_locals[return_var]

                gen_code = {"code": [], "used_vars": []}

                arg_list = []
                for a in signature["args"]:
                    new_arg = self.pick_unused_variable(a["type"], unused_locals, current_signature["args"]+local_vars)["name"]
                    arg_list.append(new_arg)
                func_call += "%s)" % ", ".join(arg_list)
                gen_code["code"].append(func_call)
                gen_code["used_vars"] = arg_list

                # Create the function's code
                self.obfuscated_functions.append(self.create_code_function([], signature, [], code_levels, add_return=True))

            # Handle MATH!
            elif r == "math":
                gen_code = self.create_code_math(unused_locals, current_signature, local_vars)

            # Handle API function calls
            elif r == "api":
                gen_code = self.create_code_api(unused_locals, current_signature, local_vars)

            # Handle conditionals
            elif r == "conditional":
                if code_levels <= 0:
                    continue

                gen_code = self.create_code_conditional([], unused_locals, current_signature, local_vars, code_levels, in_func)

            # Handle loops
            elif r == "loop":
                if code_levels <= 0:
                    continue

                gen_code = self.create_code_loop(unused_locals, current_signature, local_vars)

            # Handle string manipulations
            elif r == "string":
                gen_code = self.create_code_string_work(unused_locals, current_signature, local_vars)

            # Handle sleep
            elif r == "sleep":
                gen_code = self.create_code_sleep(unused_locals, current_signature, local_vars)

            # Handle real code
            elif r == "real":
                # If there's no real code left and all the local vars have been used, end the code block
                if (not real_code) and ((not len(unused_locals)) or (not in_func)):

                    # Add a return value if it says to
                    if add_return:
                        v1 = self.pick_unused_variable(current_signature["return"], unused_locals,
                                                       current_signature["args"]+local_vars)["name"]
                        ret["code"].append("return %s" % v1)
                    break

                # Otherwise, if there's no more real code, keep using up vars
                elif not real_code:
                    continue

                # Get rid of bracket lines and empty lines
                if real_code[0].strip() in ["{", "}", ""]:
                    del real_code[0]
                    continue

                if re.match(self.regex_conditional, real_code[0].strip()) or \
                   re.match(self.regex_loop, real_code[0].strip()) or \
                   re.match(self.regex_function, real_code[0].strip()):
                    block = {"line": real_code[0].strip(), "code_block": []}

                    end_of_block = self.find_code_block(real_code, 1)

                    cb_in_func = in_func
                    if re.match(self.regex_function, real_code[0].strip()):
                        cb_in_func = True

                    print real_code[0]
                    new_code_block = self.create_code_block(real_code[1:end_of_block], current_signature,
                                                            local_vars, False, code_levels-1, cb_in_func)
                    block["code_block"] = new_code_block["code"]

                    gen_code = {"code": [block], "used_vars": new_code_block["used_vars"]}

                    real_code = real_code[end_of_block:]

                else:
                    ret["code"].append("%s" % real_code[0].strip())
                    print real_code[0]
                    del real_code[0]

            if gen_code:
                #print "%s %s" % (type(ret), type(gen_code))
                ret["code"].extend(gen_code["code"])
                for new_arg in gen_code["used_vars"]:
                    ret["used_vars"].append(new_arg)
                    for i in range(len(unused_locals)):
                        if unused_locals[i]["name"] == new_arg:
                            del unused_locals[i]
                            break

        ret["used_vars"] = list(set(ret["used_vars"]))
        return ret

    def create_code_function(self, real_code, signature, local_vars, code_levels, add_return=False):
        func = {"line": "", "code_block": []}
        func["line"] += "func %s(" % signature["name"]

        sig_args = []
        for argument in signature["args"]:
            sig_args.append("%s %s" % (argument["type"], argument["name"]))
        func["line"] += "%s) %s" % (", ".join(sig_args), signature["return"])

        # Create the function code block
        code_block = self.create_code_block(real_code, signature, local_vars,
                                            add_return=add_return, code_levels=(code_levels-1), in_func=True)
        func["code_block"] = code_block["code"]

        return func

    def create_code_math(self, unused_locals, current_signature, local_vars):
        ret = []
        used_vars = []

        operators = {"int": ["+", "-", "*", "^", "&", "|"],
                     "float": ["+", "-", "*"],
                     "bool": ["&&", "||"]}

        code_type = operators["int"] + ["assign char"]

        op = random.choice(code_type)

        if op in operators["int"]:
            math_type = random.choice(["bool", "int", "float"])
            operator = random.choice(operators[math_type])

            v1 = self.pick_unused_variable(math_type, unused_locals, current_signature["args"]+local_vars)["name"]
            v2 = self.pick_unused_variable(math_type, unused_locals, current_signature["args"]+local_vars)["name"]
            v3 = self.pick_unused_variable(math_type, unused_locals, current_signature["args"]+local_vars)["name"]

            ret.append("%s = %s %s %s;" % (v1, v2, operator, v3))
            used_vars.extend([v2, v3])

        elif op == "assign char":
            i1 = self.pick_unused_variable("int", unused_locals, current_signature["args"]+local_vars)["name"]
            c1 = self.pick_unused_variable("char", unused_locals, current_signature["args"]+local_vars)["name"]

            ret.append("%s = %s;" % (i1, c1))
            used_vars.extend([i1, c1])

        return {"code": ret, "used_vars": used_vars}

    def create_code_api(self, current_signature, local_vars, tab="  "):
        ret = ""

        op = random.choice(["WriteFile", "CreateReg", "CreateMutex"])

        v1 = self.pick_random_variable("int", current_signature["args"], local_vars)
        v2 = self.pick_random_variable("int", current_signature["args"], local_vars)
        v3 = self.pick_random_variable("int", current_signature["args"], local_vars)

        if op == "WriteFile":
            pass
        elif op == "CreateReg":
            pass
        elif op == "CreateMutex":
            pass

        return ret

    def create_code_conditional(self, real_code, unused_locals, current_signature, local_vars, code_levels, in_func=False):
        ret = []

        v = self.pick_unused_variable("int", unused_locals, current_signature["args"]+local_vars)["name"]

        passed_local_vars = local_vars
        legit_code = self.create_code_block(real_code, current_signature, passed_local_vars, False, code_levels-1, in_func)
        if not legit_code:
            legit_code = ["pass"]

        passed_local_vars = local_vars
        fake_code = self.create_code_block([], current_signature, passed_local_vars, False, code_levels-1, in_func)
        if not fake_code:
            fake_code = ["pass"]

        b1 = self.pick_unused_variable("bool", unused_locals, current_signature["args"]+local_vars)["name"]

        r = random.randint(0, 1)
        if r == 0:
            ret.append("%s = ((%s * 0) != 0)" % (b1, v))
            ret.append({"line": "if (%s)" % b1, "code_block": fake_code["code"]})
            ret.append({"line": "else", "code_block": legit_code["code"]})
        elif r == 1:
            ret.append("%s = ((%s * 1) != %s)" % (b1, v, v))
            ret.append({"line": "if (%s)" % b1, "code_block": fake_code["code"]})
            ret.append({"line": "else", "code_block": legit_code["code"]})

        return {"code": ret, "used_vars": [b1, v]}

    def create_code_loop(self, unused_locals, current_signature, local_vars):
        return ""

    def create_code_string_work(self, unused_locals, current_signature, local_vars):
        ret = []
        used_vars = []

        op = random.choice(["strlen", "strcpy", "strncpy", "strcmp"])

        if op == "strlen":
            s1 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)["name"]
            i1 = self.pick_unused_variable("int", unused_locals, current_signature["args"]+local_vars)["name"]
            ret.append("%s = %s(%s);" % (i1, op, s1))
            used_vars.extend([s1])

        elif op == "strcpy":
            # We have to check that the destination has room for the source
            s1 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)
            s2 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)
            if s1["size"] >= s2["size"]:
                ret.append("%s(%s, %s);" % (op, s1["name"], s2["name"]))
                used_vars.extend([s2["name"]])
            else:
                ret.append("%s(%s, %s);" % (op, s2["name"], s1["name"]))
                used_vars.extend([s1["name"]])

        elif op == "strncpy":
            # We have to use the destination's size
            s1 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)["name"]
            s2 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)["name"]
            i1 = self.pick_unused_variable("int", unused_locals, current_signature["args"]+local_vars)["name"]
            ret.append("%s = strlen(%s);" % (i1, s1))
            ret.append("%s(%s, %s, %s);" % (op, s1, s2, i1))
            used_vars.extend([s1, s2, i1])

        elif op == "strcmp":
            i1 = self.pick_unused_variable("int", unused_locals, current_signature["args"]+local_vars)["name"]
            s1 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)["name"]
            s2 = self.pick_unused_variable("char*", unused_locals, current_signature["args"]+local_vars)["name"]
            ret.append("%s = %s(%s, %s);" % (i1, op, s1, s2))
            used_vars.extend([s1, s2])

        return {"code": ret, "used_vars": used_vars}

    def create_code_sleep(self, current_signature, local_vars, tab="  "):
        pass

    def pick_unused_variable(self, var_type, unused, backup):
        """
        Description:
            Pick a randomized variable to use

        :param var_type: the type of variable you want to use
        :param args: list of currently available function parameters
        :param local_vars: list of currently available local variables
        :return: string: the variable name to use
        """

        for arg in unused:
            if arg["type"] == var_type:
                return arg

        c = []
        for arg in backup:
            if arg["type"] == var_type:
                c.append(arg)

        return random.choice(c)

    def pick_random_variable(self, var_type, args, local_vars):
        """
        Description:
            Pick a randomized variable to use

        :param var_type: the type of variable you want to use
        :param args: list of currently available function parameters
        :param local_vars: list of currently available local variables
        :return: string: the variable name to use
        """

        use_me = random.randint(1, 3)

        while True:
            if use_me == 1:
                random.shuffle(args)
                for a in args:
                    if a["type"] == var_type:
                        return a["name"]
                use_me = random.randint(2, 3)

            elif use_me == 2:
                random.shuffle(local_vars)
                for b in local_vars:
                    if b["type"] == var_type:
                        return b["name"]
                use_me = 3

            elif use_me == 3:
                random.shuffle(self.code_fake_globals)
                for c in self.code_fake_globals:
                    if c["type"] == var_type:
                        return c["name"]
                use_me = 1

    def create_random_variable(self, var_type, prefix):
        """
        Description:
            Generate a randomized variable
        :param var_type: string
        :param prefix: string
        :return: dict
        """

        v = {"type": var_type, "name": ""}
        while (v["name"] == "") or (v["name"] in self.used_variables):
            v["name"] = "%s_%s" % (prefix, self.random_alphanum(8))

        if v["type"] == "bool":
            v["init_value"] = str(random.randint(0, pow(2, 32)))
            v["line"] = "%s %s = %s;" % (v["type"], v["name"], v["init_value"])

        if v["type"] == "int":
            v["init_value"] = str(random.randint(0, pow(2, 32)))
            v["line"] = "%s %s = %s;" % (v["type"], v["name"], v["init_value"])

        if v["type"] == "float":
            v["init_value"] = str(random.randint(0, pow(2, 32)))
            v["line"] = "%s %s = %s;" % (v["type"], v["name"], v["init_value"])

        elif v["type"] == "char":
            v["init_value"] = random.choice(string.ascii_letters + string.digits)
            if v["init_value"] == '\\':
                v["init_value"] = '$'
            v["line"] = "%s %s = \'%c\';" % (v["type"], v["name"], v["init_value"])

        elif v["type"] == "char*":
            v["init_value"] = self.random_alphanum(random.randint(4, 32))
            v["line"] = "%s %s = \"%s\";" % (v["type"], v["name"], v["init_value"])
            v["size"] = len(v["init_value"])

        self.used_variables.add(v["name"])

        return v

    def find_code_block(self, code_block, index):
        brackets = 1

        if not (code_block[index] == "{"):
            print "Code block did not start with brackets..."
            return None

        line_index = index+1

        while line_index < len(code_block):
            if code_block[line_index] == "{":
                brackets += 1
            elif code_block[line_index] == "}":
                brackets -= 1

            if not brackets:
                break

            line_index += 1

        return line_index

    def fill_obfuscated_code(self, code_block):
        self.obfuscated_code = []
        self.obfuscated_code.extend(self.obfuscated_prefix)
        self.obfuscated_code.extend(self.obfuscated_functions)
        self.obfuscated_code.extend(code_block)

    def fill_code_string(self, code_block, tab_count):
        ret = ""
        current_tab = self.tab_size*tab_count
        for l in code_block:
            if type(l) is str:
                ret += "%s%s\n" % (current_tab, l)

            elif type(l) is dict:
                ret += "%s%s {\n" % (current_tab, l["line"])
                ret += self.fill_code_string(l["code_block"], tab_count+1)
                ret += "%s} \n\n" % current_tab

        return ret
