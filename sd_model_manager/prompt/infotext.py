from collections import defaultdict
import re
import json
from sd_model_manager.prompt import parser


def null_handler(signum, frame):
    pass


ERROR_EXIT_CODE = 1
addnet_re = re.compile(r'^addnet_.+_\d+')
addnet_model_re = re.compile(r'(.*)\(([a-f0-9]+)\)$')
re_AND = re.compile(r"\bAND\b")
re_whitespace = re.compile(r'  +')
re_metatag = re.compile(r'\S+([^\\]):\S+')


def remove_metatags(tags):
    return [t for t in tags if not re_metatag.search(t)]


def get_negatives(line):
    negatives = line.replace("Negative prompt: ","negative:",1).strip()
    negatives = re.sub(re_whitespace, " ", negatives)
    return negatives


def get_settings(line):
    setup = line.replace(": ",":")          # Removes the space between the namespace and tag
    settings = setup.split(",")
    settings = [setting.strip().replace(" ","_") for setting in settings]
    return settings


def get_tokens(line):
    prompt = line.replace(":",";")          # Replace : to avoid unwanted namespaces
    tokens = prompt.split(",")
    tokens = [token.strip().replace(" ","_") for token in tokens]
    tokens = list(filter(lambda t: t, tokens))
    return tokens


annoying_infotext_fields = ["Wildcard prompt", "X Values", "Y Values", "Z Values"]
re_annoying_infotext_fields = re.compile(rf'({"|".join(annoying_infotext_fields)}): "[^"]*?"(?:, |$)')
re_extra_net = re.compile(r"<(\w+):([^>]+)>")


def strip_annoying_infotext_fields(settings):
    return re.sub(re_annoying_infotext_fields, "", settings)


def parse_prompt(prompt):
    res = defaultdict(list)

    def found(m):
        name = m.group(1)
        args = m.group(2)

        res[name].append(args.split(":"))

        return ""

    prompt = re.sub(re_extra_net, found, prompt)

    return prompt, res


def parse_prompts(prompts):
    res = []
    extra_data = None

    for prompt in prompts:
        updated_prompt, parsed_extra_data = parse_prompt(prompt)

        if extra_data is None:
            extra_data = parsed_extra_data

        res.append(updated_prompt)

    return res, extra_data


TEMPLATE_LABEL = "Template"
NEGATIVE_TEMPLATE_LABEL = "Negative Template"


def strip_template_info(settings) -> str:
    """dynamic-prompts"""
    split_by = None
    if (
        f"\n{TEMPLATE_LABEL}:" in settings
        and f"\n{NEGATIVE_TEMPLATE_LABEL}:" in settings
    ):
        split_by = f"{TEMPLATE_LABEL}"
    elif f"\n{NEGATIVE_TEMPLATE_LABEL}:" in settings:
        split_by = f"\n{NEGATIVE_TEMPLATE_LABEL}:"
    elif f"\n{TEMPLATE_LABEL}:" in settings:
        split_by = f"\n{TEMPLATE_LABEL}:"

    if split_by:
        settings = (
            settings.split(split_by)[0].strip()
        )
    return settings


def parse_comfyui_prompt(prompt):
    graph = json.loads(prompt)

    prompts = {id: n for id, n in graph.items() if n["class_type"] == "CLIPTextEncode" and "text" in n["inputs"]}
    ksamplers = [(id, n) for id, n in graph.items() if "KSampler" in n["class_type"] and "positive" in n["inputs"]]

    positive = None
    negative = None

    for id, ks in ksamplers:
        pos = ks["inputs"]["positive"]
        neg = ks["inputs"]["negative"]

        if isinstance(pos, list):
            id_pos = pos[0]
            if id_pos in prompts:
                positive = prompts[id_pos]["inputs"]["text"]
        elif isinstance(pos, str):
            positive = pos

        if isinstance(neg, list):
            id_neg = neg[0]
            if id_neg in prompts:
                negative = prompts[id_neg]["inputs"]["text"]
        elif isinstance(neg, str):
            negative = neg

    if positive is None:
        return set()

    tokens = set()
    settings = [] # TODO

    ts = parser.parse_prompt_attention(positive)
    full_line = ""
    for token, weight in ts:
        full_line += token + ","
    all_tokens = get_tokens(full_line.lower())
    tokens.update(all_tokens)

    all_tokens = list(tokens) + settings
    tags = [t for t in all_tokens if t]
    if negative:
        tags += ["negative:" + negative]

    tags = set([t.strip() for t in tags])
    # for r in to_remove:
    #     tags.remove(r)

    return tags


def parse_a1111_prompt(params):
    raw_prompt, extra_network_params = parse_prompt(params)

    lines = raw_prompt.split("\n")
    settings_lines = ""
    negative_prompt = ""
    negatives = None
    prompt = ""

    line_is = "positive"

    if len(lines) == 2:
        prompt = lines[0]
        negatives = get_negatives(lines[1])
    else:
        for line in lines:
            stripped_line = line.strip()
            if stripped_line == "":
                continue

            if stripped_line.startswith("Steps: "):
                line_is = "settings"
                settings_lines = stripped_line + "\n"
                continue
            if line_is == "negative":
                negatives += ", " + stripped_line
                continue
            elif line_is == "settings":
                settings_lines += stripped_line + "\n"
                continue

            if stripped_line.startswith("Negative prompt: "):
                line_is = "negative"
                negatives = get_negatives(stripped_line)
                continue

            prompt += stripped_line + "\n"

    settings_lines = strip_annoying_infotext_fields(settings_lines)
    settings_lines = strip_template_info(settings_lines)
    settings = get_settings(settings_lines.lower())

    addnet_models = []
    to_remove = []
    for tag in settings:
        tag = tag.lower()
        if addnet_re.search(tag):
            to_remove.append(tag.strip())
            if tag.startswith("addnet_model"):
                t = re.sub(addnet_re, "", tag).strip(":")
                m = addnet_model_re.search(t)
                if not m:
                    print(f"COULD NOT FIND: {t}")
                    continue
                name, hash = m.groups()
                t1 = f"addnet_model:{t}"
                t2 = f"addnet_model_name:{name}"
                t3 = f"addnet_model_hash:{hash}"
                addnet_models.append(t1)
                addnet_models.append(t2)
                addnet_models.append(t3)
    settings += addnet_models
    tokens = set()

    steps = 20
    for t in settings:
        if t.startswith("steps:"):
            steps = int(t.replace("steps:", ""))
            break

    subprompts = re_AND.split(prompt)
    if len(subprompts) > 1:
        settings.append("uses_multicond:true")

    # Reconstruct tags from parsed attention
    for parsed in parser.get_learned_conditioning_prompt_schedules(subprompts, steps):
        if len(parsed) > 1:
            settings.append("uses_prompt_editing:true")
        for t in parsed:
            step, prompt = t
            ts = parser.parse_prompt_attention(prompt)
            full_line = ""
            for token, weight in ts:
                if token == "BREAK":
                    continue
                full_line += token + ","
            all_tokens = get_tokens(full_line.lower())
            tokens.update(all_tokens)

    extra_networks = []
    for network_type, arglists in extra_network_params.items():
        for arglist in arglists:
            extra_networks.append(f"extra_networks_{network_type}:{arglist[0]}")

    all_tokens = list(tokens) + settings + extra_networks
    tags = [t for t in all_tokens if t]
    if negatives:
        tags += [negatives]

    tags = set([t.strip() for t in tags])
    for r in to_remove:
        tags.remove(r)

    return tags
