# ba_meta require api 7
# (see https://ballistica.net/wiki/meta-tag-system)

from __future__ import annotations

from typing import TYPE_CHECKING

import ba
import random
from bastd.actor.onscreentimer import OnScreenTimer
from bastd.actor.spaz import BombDiedMessage
from bastd.actor.playerspaz import PlayerSpaz
from bastd.actor import bomb as stdbomb

if TYPE_CHECKING:
	from typing import Any, Sequence


lang = ba.app.lang.language



name = '炸弹在手上'
description = ('你手上会一直冒出炸弹！\n'
			  '能活多久活多久吧！')
description_ingame = '能活多久活多久吧！'
maxbomblimit = '最大炸弹'
mbltwo = '俩个'
mblthree = '三个'
mblfour = '四个'


class NewPlayerSpaz(PlayerSpaz):

	def handlemessage(self, msg: Any) -> Any:
		if isinstance(msg, BombDiedMessage):
			self.bomb_count += 1
			self.check_avalible_bombs()
		else:
			return super().handlemessage(msg)

	def check_avalible_bombs(self) -> None:
		if not self.node:
			return
		if self.bomb_count <= 0:
			return
		if not self.node.hold_node:
			self.on_bomb_press()
			self.on_bomb_release()

	def start_bomb_checking(self) -> None:
		self.check_avalible_bombs()
		self._bomb_check_timer = ba.timer(
			0.5,
			ba.WeakCall(self.check_avalible_bombs),
			repeat=True)

	def drop_bomb(self) -> stdbomb.Bomb | None:
		lifespan = 3.0

		if self.bomb_count <= 0 or self.frozen:
			return None
		assert self.node
		pos = self.node.position_forward
		vel = self.node.velocity

		bomb_type = 'normal'

		bomb = stdbomb.Bomb(
			position=(pos[0], pos[1] - 0.0, pos[2]),
			velocity=(vel[0], vel[1], vel[2]),
			bomb_type=bomb_type,
			blast_radius=self.blast_radius,
			source_player=self.source_player,
			owner=self.node,
		).autoretain()

		ba.animate(bomb.node, 'model_scale', {
			0.0: 0.0,
			lifespan*0.1: 1.5,
			lifespan*0.5: 1.0
		})

		self.bomb_count -= 1
		bomb.node.add_death_action(
			ba.WeakCall(self.handlemessage, BombDiedMessage())
		)
		self._pick_up(bomb.node)

		for clb in self._dropped_bomb_callbacks:
			clb(self, bomb)

		return bomb


class Player(ba.Player['Team']):
	"""Our player type for this game."""

	def __init__(self) -> None:
		super().__init__()
		self.death_time: float | None = None


class Team(ba.Team[Player]):
	"""Our team type for this game."""


# ba_meta export game
class BombOnMyHeadGame(ba.TeamGameActivity[Player, Team]):

	name = name
	description = description
	scoreconfig = ba.ScoreConfig(
		label='Survived', scoretype=ba.ScoreType.MILLISECONDS, version='B'
	)
	# Show messages when players die since it's meaningful here.
	announce_player_deaths = True

	allow_mid_activity_joins = False

	@classmethod
	def get_available_settings(
		cls, sessiontype: type[ba.Session]
	) -> list[ba.Setting]:
		settings = [
			ba.IntChoiceSetting(
				maxbomblimit,
				choices=[
					('Normal', 1),
					(mbltwo, 2),
					(mblthree, 3),
					(mblfour, 4),
				],
				default=1,
			),
			ba.IntChoiceSetting(
				'Time Limit',
				choices=[
					('None', 0),
					('1 Minute', 60),
					('2 Minutes', 120),
					('5 Minutes', 300),
					('10 Minutes', 600),
					('20 Minutes', 1200),
				],
				default=0,
			),
			ba.BoolSetting('Epic Mode', default=False),
		]
		return settings

	@classmethod
	def supports_session_type(cls, sessiontype: type[ba.Session]) -> bool:
		return issubclass(sessiontype, ba.DualTeamSession) or issubclass(
			sessiontype, ba.FreeForAllSession
		)

	@classmethod
	def get_supported_maps(cls, sessiontype: type[ba.Session]) -> list[str]:
		return ba.getmaps('melee')

	def __init__(self, settings: dict):
		super().__init__(settings)
		self._max_bomb_limit = int(settings[maxbomblimit])
		self._epic_mode = bool(settings['Epic Mode'])
		self._time_limit = float(settings['Time Limit'])
		self._last_player_death_time: float | None = None
		self._timer: OnScreenTimer | None = None

		# Some base class overrides:
		self.default_music = (
			ba.MusicType.EPIC if self._epic_mode else ba.MusicType.SURVIVAL
		)
		if self._epic_mode:
			self.slow_motion = True

	def get_instance_description(self) -> str | Sequence:
		return description_ingame

	def on_begin(self) -> None:
		super().on_begin()
		self.setup_standard_time_limit(self._time_limit)
		self._timer = OnScreenTimer()
		self._timer.start()

	def spawn_player(self, player: Player) -> ba.Actor:
		from ba import _math
		from ba._gameutils import animate
		from ba._coopsession import CoopSession

		if isinstance(self.session, ba.DualTeamSession):
			position = self.map.get_start_position(player.team.id)
		else:
			# otherwise do free-for-all spawn locations
			position = self.map.get_ffa_start_position(self.players)
		angle = None
		name = player.getname()
		color = player.color
		highlight = player.highlight

		light_color = _math.normalized_color(color)
		display_color = ba.safecolor(color, target_intensity=0.75)

		spaz = NewPlayerSpaz(color=color,
							 highlight=highlight,
							 character=player.character,
							 player=player)

		player.actor = spaz
		assert spaz.node

		spaz.node.name = name
		spaz.node.name_color = display_color
		spaz.connect_controls_to_player()

		# Move to the stand position and add a flash of light.
		spaz.handlemessage(
			ba.StandMessage(
				position,
				angle if angle is not None else random.uniform(0, 360)))
		ba.playsound(self._spawn_sound, 1, position=spaz.node.position)
		light = ba.newnode('light', attrs={'color': light_color})
		spaz.node.connectattr('position', light, 'position')
		animate(light, 'intensity', {0: 0, 0.25: 1, 0.5: 0})
		ba.timer(0.5, light.delete)

		ba.timer(1.0, ba.WeakCall(spaz.start_bomb_checking))
		spaz.set_bomb_count(self._max_bomb_limit)

	def handlemessage(self, msg: Any) -> Any:
		if isinstance(msg, ba.PlayerDiedMessage):

			# Augment standard behavior.
			super().handlemessage(msg)

			curtime = ba.time()

			# Record the player's moment of death.
			# assert isinstance(msg.spaz.player
			msg.getplayer(Player).death_time = curtime

			# In co-op mode, end the game the instant everyone dies
			# (more accurate looking).
			# In teams/ffa, allow a one-second fudge-factor so we can
			# get more draws if players die basically at the same time.
			if isinstance(self.session, ba.CoopSession):
				# Teams will still show up if we check now.. check in
				# the next cycle.
				ba.pushcall(self._check_end_game)

				# Also record this for a final setting of the clock.
				self._last_player_death_time = curtime
			else:
				ba.timer(1.0, self._check_end_game)

		else:
			# Default handler:
			return super().handlemessage(msg)
		return None

	def _check_end_game(self) -> None:
		living_team_count = 0
		for team in self.teams:
			for player in team.players:
				if player.is_alive():
					living_team_count += 1
					break

		# In co-op, we go till everyone is dead.. otherwise we go
		# until one team remains.
		if isinstance(self.session, ba.CoopSession):
			if living_team_count <= 0:
				self.end_game()
		else:
			if living_team_count <= 1:
				self.end_game()


	def end_game(self) -> None:
		cur_time = ba.time()
		assert self._timer is not None
		start_time = self._timer.getstarttime()

		# Mark death-time as now for any still-living players
		# and award players points for how long they lasted.
		# (these per-player scores are only meaningful in team-games)
		for team in self.teams:
			for player in team.players:
				survived = False

				# Throw an extra fudge factor in so teams that
				# didn't die come out ahead of teams that did.
				if player.death_time is None:
					survived = True
					player.death_time = cur_time + 1

				# Award a per-player score depending on how many seconds
				# they lasted (per-player scores only affect teams mode;
				# everywhere else just looks at the per-team score).
				score = int(player.death_time - self._timer.getstarttime())
				if survived:
					score += 50  # A bit extra for survivors.
				self.stats.player_scored(player, score, screenmessage=False)

		# Stop updating our time text, and set the final time to match
		# exactly when our last guy died.
		self._timer.stop(endtime=self._last_player_death_time)

		# Ok now calc game results: set a score for each team and then tell
		# the game to end.
		results = ba.GameResults()

		# Remember that 'free-for-all' mode is simply a special form
		# of 'teams' mode where each player gets their own team, so we can
		# just always deal in teams and have all cases covered.
		for team in self.teams:

			# Set the team score to the max time survived by any player on
			# that team.
			longest_life = 0.0
			for player in team.players:
				assert player.death_time is not None
				longest_life = max(longest_life, player.death_time - start_time)

			# Submit the score value in milliseconds.
			results.set_team_score(team, int(1000.0 * longest_life))

		self.end(results=results)
