# smart/ - optional "Smart" features (all OFF by default, switched on from the Smart page).
#
# The bot calls the hooks below from a handful of places (farming.py, recovery.py, upgrades.py and the
# attack strategies). Every hook is wrapped: a Smart feature may fail, but it can never crash or
# change the bot when its switch is off.
#
#   selfheal.py    re-crop a button picture when a game update changed it (OCR)
#   canary.py      read-only "what broke" check after a game update
#   lost.py        get home from an unknown screen with safe taps instead of restarting the game
#   spend.py       stop farming a resource whose storage is full
#   learn.py       log every attack; skip bases the chosen strategy keeps failing on
#   economy.py     pick bases by loot per hour (break-even rule); rest when every storage is full
#   ledger.py      check every attack's numbers against the game's own arithmetic
#   basereader.py  pick the entry side from the base's real deploy line
#   planner.py     never-idle builders, upgrade order, no hero upgrades during a war
#   events.py      session replay timeline (HTML) and the attack log
#   remote.py      Telegram remote control and Discord messages
#   goals.py       plain-language goals -> settings changes (keyword rules)
#   farm.py        one bot per emulator instance
#   webdash.py     web dashboard / headless mode
import time
import traceback

_last_error = {}


def _guard(name, default=None):
    """Decorator: run a hook, log a failure at most once a minute, return `default` on error."""
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except BaseException as e:          # noqa: BLE001 - re-raise the bot's own control flow
                if e.__class__.__name__ in ('BotStopped', 'KeyboardInterrupt', 'SystemExit'):
                    raise
                now = time.time()
                if now - _last_error.get(name, 0) > 60:
                    _last_error[name] = now
                    print(f'[SMART] {name} failed: {e.__class__.__name__}: {e}')
                    traceback.print_exc()
                return default
        return inner
    return wrap


def on(cfg, key):
    return bool((cfg or {}).get(key, False))


@_guard('search')
def on_search_loot(cfg, vision, gold, elixir, dark, strategy=None):
    """'skip' when a Smart rule says this base is not worth attacking, else None."""
    from smart import economy, learn, ledger, spend
    verdict = None
    econ = None
    if on(cfg, 'SMART_LEDGER') or on(cfg, 'SMART_ECON_NEXT'):
        ledger.note_offer(gold, elixir, dark, vision)
    if on(cfg, 'SMART_ECON_NEXT'):                   # always shown the base, so it keeps learning
        econ = economy.verdict(cfg, vision, gold, elixir, dark, spend.full())
    if on(cfg, 'SMART_SPEND_AWARE'):
        verdict = spend.verdict(cfg, vision, gold, elixir, dark)
    if verdict is None and on(cfg, 'SMART_LEARN_SKIP'):
        verdict = learn.verdict(cfg, vision, strategy)
    verdict = verdict or econ
    learn.remember_offer(vision, gold, elixir, dark)
    return verdict


@_guard('home')
def on_home(cfg, vision, stats=None, pause_if_needed=None):
    """On the home village. Returns a farming gate ('RECOVERY' / 'END_CONDITION') or None."""
    from smart import canary, economy, ledger, spend
    full = None
    if any(on(cfg, k) for k in ('SMART_SPEND_AWARE', 'SMART_ECON_NEXT', 'SMART_ECON_IDLE_WHEN_FULL',
                                'SMART_LEDGER')):
        full = spend.read_home(vision)
    if on(cfg, 'SMART_LEDGER'):
        ledger.note_home(cfg, vision, full)
    if on(cfg, 'SMART_CANARY'):
        canary.check_version(cfg, vision)
    return economy.idle_gate(cfg, vision, full, pause_if_needed)


@_guard('battle end')
def on_battle_end(cfg, vision, stats, strategy, stars, gold, elixir, dark):
    from smart import economy, events, learn, ledger, remote
    if on(cfg, 'SMART_LEDGER') or on(cfg, 'SMART_ECON_NEXT'):
        ledger.note_battle_end(cfg, vision, strategy, stars, gold, elixir, dark,
                               quiet=not on(cfg, 'SMART_LEDGER'))
    if on(cfg, 'SMART_ECON_NEXT'):
        economy.note_battle_end()
    entry = learn.record(cfg, vision, strategy, stars, gold, elixir, dark,
                         write=on(cfg, 'SMART_LEARN_LOG') or on(cfg, 'SMART_LEARN_SKIP'))
    if on(cfg, 'SMART_REPLAY'):
        events.record('attack', frame=vision.grab(), **entry)
    remote.notify_attack(cfg, entry)


@_guard('lost', default=False)
def on_lost(cfg, vision, adb):
    """Called before the game is force-restarted. True when the bot is back on the home village."""
    from smart import events, lost
    if on(cfg, 'SMART_REPLAY'):
        events.record('recovery', frame=vision.grab(), note='The bot lost its way and started recovery')
    if on(cfg, 'SMART_RESCUE'):
        return bool(lost.rescue(cfg, vision, adb))
    return False


@_guard('self-heal', default=False)
def heal(cfg, vision, key):
    """Try to repair one template after it stopped matching. True when a new picture was saved."""
    if not on(cfg, 'SMART_SELF_HEAL'):
        return False
    from smart import selfheal
    return bool(selfheal.heal(cfg, vision, key))


@_guard('base reader')
def entry_point(cfg, vision, th_pos):
    """Point used to pick the attack side (defaults to the Town Hall position)."""
    if str((cfg or {}).get('SMART_BASE_READER', 'off')) != 'redline':
        return th_pos
    from smart import basereader
    return basereader.entry_point(cfg, vision, th_pos) or th_pos


def config():
    """The running bot's merged config (empty when the bot is not running)."""
    try:
        import main
        return main.active_config or {}
    except Exception:
        return {}
