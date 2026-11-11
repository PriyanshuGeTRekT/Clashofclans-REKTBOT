# attack.dragon - Reconstructed from attack.dragon.dis.txt (Pyarmor 015394, Python 3.10).
import random
from attack.geometry import THREE_SIDES, FOUR_SIDES
from attack.attacklogic import (wait, closest_side_index, closest_side_midpoint, read_battle_snapshot,
                                deploy_troop, deploy_heroes, retap_heroes, deploy_event_troops_air,
                                build_line_points, deploy_siege_if_present, deploy_dragon_spells,
                                dump_remaining_spells_on_th, dump_remaining_troops,
                                closest_point_on_line_with_margin, set_attack_runtime_settings,
                                wait_before_retap, get_troop_drop_width)

AIR_TROOP_WIDTH = 360
DROP_SPEED = 0.5
FALLBACK_DRAGON = 11
FALLBACK_BALLOON = 16          # defined but unused (balloon count has no OCR fallback)


def _build_dynamic_hero_lists(tabs):
    # Returns (main_heroes, duke_heroes) as lists of {'name': ...} dicts.
    # Main heroes in fixed priority order, then any other detected hero_* tabs
    # (alphabetical). 'hero_duke' is handled separately.
    priority = ['hero_queen', 'hero_king', 'hero_warden', 'hero_prince', 'hero_rc']
    present = [k for k in tabs.keys() if k.startswith('hero_') and k != 'hero_duke']
    ordered = [h for h in priority if h in present]
    ordered.extend(sorted(h for h in present if h not in ordered))
    main_heroes = [{'name': h} for h in ordered]
    duke_heroes = [{'name': 'hero_duke'}] if 'hero_duke' in tabs else []
    return (main_heroes, duke_heroes)


def run_attack(adb, vision, active_config=None):
    v = vision                       # `adb` argument is unused
    set_attack_runtime_settings(active_config)
    print('=== DRAGON ATTACK START ===')
    tabs = v.detect_tabs()
    # Same hand-off the other way: an Electro Dragon army goes to the E-Drag strategy.
    if 'troop_dragon' not in tabs and 'troop_edragon' in tabs:
        print('[DRAGON] No Dragons in the army but Electro Dragons are: using the Electro Dragon strategy')
        from attack import edragon
        edragon.run_attack(adb, vision, active_config)
        return 'edragon'          # strategy actually used (farming logs it)
    main_heroes, duke_heroes = _build_dynamic_hero_lists(tabs)
    snapshot = read_battle_snapshot(v, tabs, log_prefix='DRAGON')
    main_count = snapshot.get('troop_dragon', 0)
    balloon_count = snapshot.get('troop_balloon', 0)
    th_pos = v.get_townhall_pos()
    width = get_troop_drop_width(AIR_TROOP_WIDTH)

    # Pick the one of the 3 attack sides whose midpoint is nearest the Town Hall,
    # and the point on that edge nearest the TH (kept width/2 from the ends).
    side_idx = closest_side_index(th_pos, THREE_SIDES)
    side_line = THREE_SIDES[side_idx]
    center = closest_point_on_line_with_margin(th_pos, side_line, width / 2)

    if not main_count or main_count <= 0:
        main_count = FALLBACK_DRAGON
        print('[DRAGON] DRAGON OCR failed, using fallback:', main_count)
        check_popup = getattr(v, 'check_error_popup_once', None)
        if callable(check_popup):
            check_popup()

    main_line_points = build_line_points(side_line, center=center, width=width, count=main_count)
    balloon_line_points = build_line_points(side_line, center=center, width=width, count=balloon_count)

    # 1) main air troop line
    if 'troop_dragon' in tabs:
        deploy_troop(tabs['troop_dragon'], main_line_points[:main_count])
        snapshot['troop_dragon'] = max(0, int(snapshot.get('troop_dragon', 0)) - int(main_count))
    wait(0.6)

    # 1b) FIX: Dragon Riders ride with the main line. They used to wait for the final dump, i.e. after
    # every hero and spell had gone in, and arrived alone (1-2 stars with a Dragon + Rider army).
    rider_count = int(snapshot.get('troop_dragon_rider', 0) or 0)
    if rider_count > 0 and 'troop_dragon_rider' in tabs:
        deploy_troop(tabs['troop_dragon_rider'],
                     build_line_points(side_line, center=center, width=width, count=rider_count))
        snapshot['troop_dragon_rider'] = 0

    # 2) balloons on the same line
    if 'troop_balloon' in tabs:
        deploy_troop(tabs['troop_balloon'], balloon_line_points[:balloon_count])
        snapshot['troop_balloon'] = max(0, int(snapshot.get('troop_balloon', 0)) - int(balloon_count))
    wait(0.8)

    # 3) event troops along the same side (centered on side midpoint)
    deploy_event_troops_air(tabs, v, side_line, snapshot_counts=snapshot)
    wait(0.5)

    # 4) heroes at the point of the side closest to the TH (margin 0)
    hero_point = closest_point_on_line_with_margin(th_pos, side_line, 0)
    deploy_heroes(tabs, hero_point, main_heroes)

    # 5) "hero_duke": dropped at the midpoint of a random neighbouring side (+-1) of the 4-side diamond
    if duke_heroes:
        four_idx = closest_side_index(th_pos, FOUR_SIDES)
        duke_idx = (four_idx + random.choice([-1, 1])) % len(FOUR_SIDES)
        duke_point = closest_side_midpoint(th_pos, [FOUR_SIDES[duke_idx]])
        deploy_heroes(tabs, duke_point, duke_heroes)

    # 6) siege machine at hero point, then rage/freeze pattern toward TH
    deploy_siege_if_present(tabs, hero_point, v)
    deploy_dragon_spells(tabs, center, th_pos, spell_counts=snapshot)

    # 7) re-read spells and dump everything left on the Town Hall
    spell_snapshot = read_battle_snapshot(v, tabs, prefixes=('spell_',), log_prefix=None)
    dump_remaining_spells_on_th(v, tabs, th_pos, spell_counts=spell_snapshot)

    # 8) hero abilities, leftovers, duke ability
    wait_before_retap(1.0)
    retap_heroes(tabs, main_heroes)
    dump_remaining_troops(tabs, v, side_line=side_line, center=center, troop_counts=snapshot, width=AIR_TROOP_WIDTH)
    retap_heroes(tabs, duke_heroes)
    print('=== DRAGON ATTACK FINISHED ===')
