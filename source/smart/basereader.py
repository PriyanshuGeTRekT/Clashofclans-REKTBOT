# smart/basereader.py - let Claude read the enemy base and pick the side to attack from.
#
# The dragon strategies normally start from the side nearest the Town Hall. With the base reader
# set to "Claude", the bot shows Claude the base once per attack (one API call) and starts from the
# side Claude judges weakest against air troops. The answer is turned into a point far out on that
# side; the strategy then picks its nearest deployment edge exactly as it does for the Town Hall.
CENTRE = (800, 430)
REACH = {'top_left': (-520, -330), 'top_right': (520, -330),
         'bottom_left': (-520, 330), 'bottom_right': (520, 330)}
SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['side', 'reason'],
    'properties': {'side': {'type': 'string', 'enum': list(REACH)},
                   'reason': {'type': 'string', 'description': 'One short sentence'}},
}
PROMPT = (
    'This is a Clash of Clans enemy base seen during the scouting phase (1600x900). The base is a '
    'diamond; its four edges face top_left, top_right, bottom_left and bottom_right of the screen. '
    'An air army (dragons / electro dragons with heroes) will be dropped along ONE edge and fly '
    'towards the Town Hall. Pick the edge that gives the best result: fewest Air Defenses, Air '
    'Sweepers pointing away, Inferno Towers and Scattershots far from the entry, and a short path '
    'to the Town Hall.'
)


def entry_point(cfg, vision, th_pos):
    from smart import ai
    answer = ai.ask_json(cfg, PROMPT, SCHEMA, image_bgr=vision.grab())
    if not answer or answer.get('side') not in REACH:
        return None
    dx, dy = REACH[answer['side']]
    print(f"[SMART] Base reader: attacking from {answer['side'].replace('_', ' ')} ({answer.get('reason')})")
    return CENTRE[0] + dx, CENTRE[1] + dy
