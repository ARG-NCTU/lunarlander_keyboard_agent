import math
import warnings
from typing import TYPE_CHECKING, Optional

import numpy as np

import gymnasium as gym
from gymnasium import error, spaces
from gymnasium.error import DependencyNotInstalled
from gymnasium.utils import EzPickle, colorize
from gymnasium.utils.step_api_compatibility import step_api_compatibility

from gymnasium.envs.box2d.lunar_lander import LunarLander
from gymnasium.envs.box2d.lunar_lander import ContactDetector 
from gymnasium.envs.box2d.lunar_lander import VIEWPORT_W, VIEWPORT_H, SCALE, INITIAL_RANDOM, LEG_AWAY, LEG_DOWN, LEG_W, LEG_H, LEG_SPRING_TORQUE, LANDER_POLY, FPS, MAIN_ENGINE_POWER, SIDE_ENGINE_AWAY, SIDE_ENGINE_HEIGHT, SIDE_ENGINE_POWER

try:
    import Box2D
    from Box2D.b2 import (
        circleShape,
        contactListener,
        edgeShape,
        fixtureDef,
        polygonShape,
        revoluteJointDef,
    )
except ImportError as e:
    raise DependencyNotInstalled(
        "Box2D is not installed, run `pip install gymnasium[box2d]`"
    ) from e

class UavLander(LunarLander):
    # TODO: Please add docstrings for this class
    """
    Description:
        The agent (a uav-lander) is started at a random position above the surface.
        The agent is given a reward of 100 points if it lands safely on the boat platformn.
        The agent is given a reward of -100 points if it crashes on the moon's surface.

    Atributes:
        world: Box2D.b2World
        lander: Box2D.b2Body
        lags: Box2D.b2Body

    Methods:
        step
        reset
        render
        close

    Usage:
    >>> env = UavLander()
    >>> env.reset()
    >>> env.render()
    Expected output
    """
    def _gen_uav_terrain(self, terrain_node:int = 30, flat_platform:bool = True)->None:
        W = VIEWPORT_W / SCALE
        H = VIEWPORT_H / SCALE
        CHUNKS = terrain_node # originally 1_gen_uav_lander1
        width_para = 6

        height = self.np_random.uniform(0, H / 2, size=(CHUNKS + 1,)) # ground height, random points(CHUNKS + 1), 
                                                                      # from 0 to H / 2
        chunk_x = [W / (CHUNKS - 1) * i for i in range(CHUNKS)] # ground got CHUNKS point distributed evenly

        # helipad is not in the middle of the ground, it is in the middle of the screen
        smooth_y = [
            0.33 * (height[i - 1] + height[i + 0] + height[i + 1])
            for i in range(CHUNKS)
        ]
        height[CHUNKS // 2 + 0] = self.np_random.uniform(H/2, H *3 / 5, size = 1)[0]
        self.helipad_y = height[CHUNKS // 2 + 0]
        width_node = (CHUNKS // width_para - 1) // 2
        self.helipad_x1 = chunk_x[CHUNKS // 2 - width_node] #flag 1
        self.helipad_x2 = chunk_x[CHUNKS // 2 + width_node] #flag 2

        smooth_y[CHUNKS // 2 + 0] = self.helipad_y

        angle = 0
        if not flat_platform:
            angle = self.np_random.uniform(-math.pi / 6, math.pi / 6, size = 1)[0]

        diff_high = math.tan(angle) * W / (CHUNKS - 1)
        for i in range(width_node):
            smooth_y[CHUNKS // 2 - (i+1)] = self.helipad_y - diff_high * (i+1)
            smooth_y[CHUNKS // 2 + (i+1)] = self.helipad_y + diff_high * (i+1)

        self.moon = self.world.CreateStaticBody(
            shapes=edgeShape(vertices=[(0, 0), (W, 0)])
        )
        self.sky_polys = []
        for i in range(CHUNKS - 1):
            p1 = (chunk_x[i], smooth_y[i])
            p2 = (chunk_x[i + 1], smooth_y[i + 1])
            self.moon.CreateEdgeFixture(vertices=[p1, p2], density=0, friction=0.1)
            self.sky_polys.append([p1, p2, (p2[0], H), (p1[0], H)])

        self.moon.color1 = (0.0, 0.0, 0.0)
        self.moon.color2 = (0.0, 0.0, 0.0)

    def _gen_uav_lander(self)->None:
        initial_y = VIEWPORT_H / SCALE
        self.lander: Box2D.b2Body = self.world.CreateDynamicBody(
            position=(VIEWPORT_W / SCALE / 2, initial_y),
            angle=0.0,
            fixtures=fixtureDef(
                shape=polygonShape(
                    vertices=[(x / SCALE, y / SCALE) for x, y in LANDER_POLY]
                ),
                density=5.0,
                friction=0.1,
                categoryBits=0x0010,
                maskBits=0x001,  # collide only with ground
                restitution=0.0,
            ),  # 0.99 bouncy
        )
        self.lander.color1 = (128, 102, 230)
        self.lander.color2 = (77, 77, 128)
        self.lander.ApplyForceToCenter(
            (
                self.np_random.uniform(-INITIAL_RANDOM, INITIAL_RANDOM),
                self.np_random.uniform(-INITIAL_RANDOM, INITIAL_RANDOM),
            ),
            True,
        )

        self.legs = []
        for i in [-1, +1]:
            leg = self.world.CreateDynamicBody(
                position=(VIEWPORT_W / SCALE / 2 - i * LEG_AWAY / SCALE, initial_y),
                angle=(i * 0.05),
                fixtures=fixtureDef(
                    shape=polygonShape(box=(LEG_W / SCALE, LEG_H / SCALE)),
                    density=1.0,
                    restitution=0.0,
                    categoryBits=0x0020,
                    maskBits=0x001,
                ),
            )
            leg.ground_contact = False
            leg.color1 = (128, 102, 230)
            leg.color2 = (77, 77, 128)
            rjd = revoluteJointDef(
                bodyA=self.lander,
                bodyB=leg,
                localAnchorA=(0, 0),
                localAnchorB=(i * LEG_AWAY / SCALE, LEG_DOWN / SCALE),
                enableMotor=True,
                enableLimit=True,
                maxMotorTorque=LEG_SPRING_TORQUE,
                motorSpeed=+0.3 * i,  # low enough not to jump back into the sky
            )
            if i == -1:
                rjd.lowerAngle = (
                    +0.9 - 0.5
                )  # The most esoteric numbers here, angled legs have freedom to travel within
                rjd.upperAngle = +0.9
            else:
                rjd.lowerAngle = -0.9
                rjd.upperAngle = -0.9 + 0.5
            leg.joint = self.world.CreateJoint(rjd)
            self.legs.append(leg)

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ):
        super().reset(seed=seed)
        self._destroy()
        self.world.contactListener_keepref = ContactDetector(self)
        self.world.contactListener = self.world.contactListener_keepref
        self.game_over = False
        self.prev_shaping = None

        self._gen_uav_terrain(terrain_node=90, flat_platform=False)
        self._gen_uav_lander()

        self.drawlist = [self.lander] + self.legs # list of Box2D.b2Body

        if self.render_mode == "human":
            self.render()
        return self.step(np.array([0, 0]) if self.continuous else 0)[0], {}
    

    #=======================================gen=engine====================================
    # def step(self, action):
    #     assert self.lander is not None

    #     # Update wind
    #     assert self.lander is not None, "You forgot to call reset()"
    #     if self.enable_wind and not (
    #         self.legs[0].ground_contact or self.legs[1].ground_contact
    #     ):
    #         # the function used for wind is tanh(sin(2 k x) + sin(pi k x)),
    #         # which is proven to never be periodic, k = 0.01
    #         wind_mag = (
    #             math.tanh(
    #                 math.sin(0.02 * self.wind_idx)
    #                 + (math.sin(math.pi * 0.01 * self.wind_idx))
    #             )
    #             * self.wind_power
    #         )
    #         self.wind_idx += 1
    #         self.lander.ApplyForceToCenter(
    #             (wind_mag, 0.0),
    #             True,
    #         )

    #         # the function used for torque is tanh(sin(2 k x) + sin(pi k x)),
    #         # which is proven to never be periodic, k = 0.01
    #         torque_mag = math.tanh(
    #             math.sin(0.02 * self.torque_idx)
    #             + (math.sin(math.pi * 0.01 * self.torque_idx))
    #         ) * (self.turbulence_power)
    #         self.torque_idx += 1
    #         self.lander.ApplyTorque(
    #             (torque_mag),
    #             True,
    #         )

    #     if self.continuous:
    #         action = np.clip(action, -1, +1).astype(np.float32)
    #     else:
    #         assert self.action_space.contains(
    #             action
    #         ), f"{action!r} ({type(action)}) invalid "

    #     # Engines
    #     tip = (math.sin(self.lander.angle), math.cos(self.lander.angle))
    #     side = (-tip[1], tip[0])
    #     dispersion = [self.np_random.uniform(-1.0, +1.0) / SCALE for _ in range(2)]

    #     m_power = 0.0
    #     if (self.continuous and action[0] > 0.0) or (
    #         not self.continuous and action == 2
    #     ):
    #         # Main engine
    #         if self.continuous:
    #             m_power = (np.clip(action[0], 0.0, 1.0) + 1.0) * 0.5  # 0.5..1.0
    #             assert m_power >= 0.5 and m_power <= 1.0
    #         else:
    #             m_power = 1.0
    #         # 4 is move a bit downwards, +-2 for randomness
    #         ox = tip[0] * (4 / SCALE + 2 * dispersion[0]) + side[0] * dispersion[1]
    #         oy = -tip[1] * (4 / SCALE + 2 * dispersion[0]) - side[1] * dispersion[1]
    #         impulse_pos = (self.lander.position[0] + ox, self.lander.position[1] + oy)
    #         p = self._create_particle(
    #             3.5,  # 3.5 is here to make particle speed adequate
    #             impulse_pos[0],
    #             impulse_pos[1],
    #             m_power,
    #         )  # particles are just a decoration
    #         p.ApplyLinearImpulse(
    #             (ox * MAIN_ENGINE_POWER * m_power, oy * MAIN_ENGINE_POWER * m_power),
    #             impulse_pos,
    #             True,
    #         )
    #         self.lander.ApplyLinearImpulse(
    #             (-ox * MAIN_ENGINE_POWER * m_power, -oy * MAIN_ENGINE_POWER * m_power),
    #             impulse_pos,
    #             True,
    #         )

    #     s_power = 0.0
    #     if (self.continuous and np.abs(action[1]) > 0.5) or (
    #         not self.continuous and action in [1, 3]
    #     ):
    #         # Orientation engines
    #         if self.continuous:
    #             direction = np.sign(action[1])
    #             s_power = np.clip(np.abs(action[1]), 0.5, 1.0)
    #             assert s_power >= 0.5 and s_power <= 1.0
    #         else:
    #             direction = action - 2
    #             s_power = 1.0
    #         ox = tip[0] * dispersion[0] + side[0] * (
    #             3 * dispersion[1] + direction * SIDE_ENGINE_AWAY / SCALE
    #         )
    #         oy = -tip[1] * dispersion[0] - side[1] * (
    #             3 * dispersion[1] + direction * SIDE_ENGINE_AWAY / SCALE
    #         )
    #         impulse_pos = (
    #             self.lander.position[0] + ox - tip[0] * 17 / SCALE,
    #             self.lander.position[1] + oy + tip[1] * SIDE_ENGINE_HEIGHT / SCALE,
    #         )
    #         p = self._create_particle(0.7, impulse_pos[0], impulse_pos[1], s_power)
    #         p.ApplyLinearImpulse(
    #             (ox * SIDE_ENGINE_POWER * s_power, oy * SIDE_ENGINE_POWER * s_power),
    #             impulse_pos,
    #             True,
    #         )
    #         self.lander.ApplyLinearImpulse(
    #             (-ox * SIDE_ENGINE_POWER * s_power, -oy * SIDE_ENGINE_POWER * s_power),
    #             impulse_pos,
    #             True,
    #         )

    #     self.world.Step(1.0 / FPS, 6 * 30, 2 * 30)

    #     pos = self.lander.position
    #     vel = self.lander.linearVelocity
    #     state = [
    #         (pos.x - VIEWPORT_W / SCALE / 2) / (VIEWPORT_W / SCALE / 2),
    #         (pos.y - (self.helipad_y + LEG_DOWN / SCALE)) / (VIEWPORT_H / SCALE / 2),
    #         vel.x * (VIEWPORT_W / SCALE / 2) / FPS,
    #         vel.y * (VIEWPORT_H / SCALE / 2) / FPS,
    #         self.lander.angle,
    #         20.0 * self.lander.angularVelocity / FPS,
    #         1.0 if self.legs[0].ground_contact else 0.0,
    #         1.0 if self.legs[1].ground_contact else 0.0,
    #     ]
    #     assert len(state) == 8

    #     reward = 0
    #     shaping = (
    #         -100 * np.sqrt(state[0] * state[0] + state[1] * state[1])
    #         - 100 * np.sqrt(state[2] * state[2] + state[3] * state[3])
    #         - 100 * abs(state[4])
    #         + 10 * state[6]
    #         + 10 * state[7]
    #     )  # And ten points for legs contact, the idea is if you
    #     # lose contact again after landing, you get negative reward
    #     if self.prev_shaping is not None:
    #         reward = shaping - self.prev_shaping
    #     self.prev_shaping = shaping

    #     reward -= (
    #         m_power * 0.30
    #     )  # less fuel spent is better, about -30 for heuristic landing
    #     reward -= s_power * 0.03

    #     terminated = False
    #     if self.game_over or abs(state[0]) >= 1.0:
    #         terminated = True
    #         reward = -100
    #     if not self.lander.awake:
    #         terminated = True
    #         reward = +100

    #     if self.render_mode == "human":
    #         self.render()
    #     return np.array(state, dtype=np.float32), reward, terminated, False, {}