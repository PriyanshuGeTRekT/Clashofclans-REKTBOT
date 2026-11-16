add any new tabs in here that may be missing, these will overwrite the exe. adding them here the bot will automatically update and deploy the new troops.

crop size should be 110x70

naming format should be the following

event_(name)
hero_(name)
troop_(name)
spell_(name)
squad_(name)

Clash of Titans update (16 Nov 2026) - cards the bot cannot know yet (crop them from a battle screenshot
once your game shows them, 110x70, and save them here with these names):
- spell_heroic.png    Heroic Spell (TH17+). 50% Loot Maxxing casts it on the heroes' path, like Rage.
- squad_<name>.png    Squads (TH8+), e.g. squad_dragon.png, squad_barch.png. One tap deploys the whole
                      group; 50% Loot Maxxing deploys them round the three sides with the troops.
Town Hall 19 itself goes in templates/townhall/th19.png (and th19_barbarian / th19_archer / th19_wizard
for the troop skins). Battles against an unknown Town Hall save the scouting screen in logs/th_unknown/.
The 12 Squads at launch: barch, giant_wizard, wall_breaker, minion, balloon, golem_witch, hog_rider, miner,
healer, pekka_titan, dragon, baby_dragon (so squad_barch.png, squad_dragon.png, ...).

Until a card has a picture here, 50% Loot Maxxing still uses it: every card in the bar with a count
("x3") that the bot does not recognise is played too - troop and Squad cards round the three sides,
spell cards on the heroes' path. The other strategies only use the cards they know.
