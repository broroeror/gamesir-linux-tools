"""GameSir vendor support: the 0xFFF0 vendor command channel and its register maps.

Module layout:
  control/config/enhanced/motion/macro  — shared across GameSir models; the
      per-model differences are DATA, carried by controller_profile's
      ControllerProfile instances (addresses + capability flags).
  flash                                 — firmware backup/restore (JieLi BR23).
  models/<model>/                       — the genuinely model-specific pieces,
      i.e. lighting (the Cyclone's keyframe RGB vs the 8K's home ring) and
      captured factory baselines.
"""
