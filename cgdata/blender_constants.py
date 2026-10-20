"""Constants shared between the Blender-side kits and the plain-Python tools
(which can't import bpy). Keep in sync with blender/kits/character.py."""

# OpenPose-style limb colors for the pose-control video: (bone, RGB).
POSE_LIMBS = [("neck", (255, 0, 0)), ("head", (255, 85, 0)), ("chest", (255, 170, 0)), ("spine", (255, 255, 0)),
              ("upper_arm.R", (170, 255, 0)), ("forearm.R", (85, 255, 0)), ("hand.R", (0, 255, 0)),
              ("upper_arm.L", (0, 255, 85)), ("forearm.L", (0, 255, 170)), ("hand.L", (0, 255, 255)),
              ("thigh.R", (0, 170, 255)), ("shin.R", (0, 85, 255)), ("foot.R", (0, 0, 255)),
              ("thigh.L", (85, 0, 255)), ("shin.L", (170, 0, 255)), ("foot.L", (255, 0, 255))]
