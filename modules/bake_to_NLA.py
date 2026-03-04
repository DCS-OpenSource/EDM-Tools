# SPDX-License-Identifier: MIT
# EDM Tools – NLA Animation Baker

import bpy
from bpy.props import PointerProperty

BAKE_SUFFIX = "_BAKED"


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def get_active_armature(context):
    obj = context.object
    return obj if obj and obj.type == 'ARMATURE' else None


def ensure_anim(obj):
    if not obj.animation_data:
        obj.animation_data_create()
    return obj.animation_data


def mute_all_strips(anim):

    states = []

    for track in anim.nla_tracks:
        for strip in track.strips:
            states.append((strip, strip.mute))
            strip.mute = True

    return states


def restore_strip_states(states):

    for strip, state in states:
        strip.mute = state


# -------------------------------------------------------
# Push Action
# -------------------------------------------------------

class EDMTOOLS_OT_push_action(bpy.types.Operator):

    bl_idname = "edmtools.push_action_to_nla"
    bl_label = "Push Current Action to NLA"

    def execute(self, context):

        arm = get_active_armature(context)

        if not arm:
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        anim = ensure_anim(arm)

        if not anim.action:
            self.report({'WARNING'}, "No active action")
            return {'CANCELLED'}

        action = anim.action

        track = anim.nla_tracks.new()
        track.name = action.name

        start, end = action.frame_range

        strip = track.strips.new(
            action.name,
            int(start),
            action
        )

        strip.frame_end = int(end)

        anim.action = None

        self.report({'INFO'}, f"Pushed {action.name}")

        return {'FINISHED'}


# -------------------------------------------------------
# Bake
# -------------------------------------------------------

class EDMTOOLS_OT_bake_nla(bpy.types.Operator):

    bl_idname = "edmtools.bake_nla"
    bl_label = "Bake NLA Strips"

    def execute(self, context):

        arm = get_active_armature(context)

        if not arm:
            self.report({'ERROR'}, "Select an armature")
            return {'CANCELLED'}

        anim = ensure_anim(arm)

        strips = []

        for track in anim.nla_tracks:
            for strip in track.strips:

                if strip.action.name.endswith(BAKE_SUFFIX):
                    continue

                strips.append((track, strip))

        if not strips:
            self.report({'WARNING'}, "Nothing to bake")
            return {'CANCELLED'}

        baked = []

        for track, strip in strips:

            action = strip.action

            start = int(strip.frame_start)
            end = int(strip.frame_end)

            baked_name = action.name + BAKE_SUFFIX
            baked_action = bpy.data.actions.new(baked_name)

            # preserve original
            action.use_fake_user = True

            states = mute_all_strips(anim)
            strip.mute = False

            anim.action = baked_action

            bpy.ops.nla.bake(
                frame_start=start,
                frame_end=end,
                only_selected=False,
                visual_keying=True,
                clear_constraints=False,
                use_current_action=True,
                bake_types={'POSE'}
            )

            restore_strip_states(states)

            track.strips.remove(strip)

            baked.append((baked_action, start, end))

        # remove empty tracks
        for track in list(anim.nla_tracks):
            if not track.strips:
                anim.nla_tracks.remove(track)

        # create baked tracks
        for action, start, end in baked:

            track = anim.nla_tracks.new()
            track.name = action.name

            strip = track.strips.new(
                action.name,
                start,
                action
            )

            strip.frame_end = end

        anim.action = None

        self.report({'INFO'}, f"Baked {len(baked)} strips")

        return {'FINISHED'}


# -------------------------------------------------------
# Unbake
# -------------------------------------------------------

class EDMTOOLS_OT_unbake_nla(bpy.types.Operator):

    bl_idname = "edmtools.unbake_nla"
    bl_label = "Unbake NLA Strips"

    def execute(self, context):

        arm = get_active_armature(context)

        if not arm or not arm.animation_data:
            return {'CANCELLED'}

        anim = arm.animation_data

        restored = []
        baked_actions = []

        for track in list(anim.nla_tracks):

            for strip in list(track.strips):

                action = strip.action

                if not action or not action.name.endswith(BAKE_SUFFIX):
                    continue

                baked_actions.append(action)

                base_name = action.name[:-len(BAKE_SUFFIX)]
                original = bpy.data.actions.get(base_name)

                if original:

                    start = int(strip.frame_start)
                    end = int(strip.frame_end)

                    restored.append((original, start, end))

                track.strips.remove(strip)

            if not track.strips:
                anim.nla_tracks.remove(track)

        # restore original strips
        for action, start, end in restored:

            track = anim.nla_tracks.new()
            track.name = action.name

            strip = track.strips.new(
                action.name,
                start,
                action
            )

            strip.frame_end = end

        # delete baked actions to prevent .001 duplicates
        for action in baked_actions:
            bpy.data.actions.remove(action)

        self.report({'INFO'}, f"Restored {len(restored)} actions")

        return {'FINISHED'}

# -------------------------------------------------------
# UI
# -------------------------------------------------------

class EDMTOOLS_PT_nla_panel(bpy.types.Panel):

    bl_label = "Bake NLA Animations"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EDM Tools"
    bl_parent_id = "EDMTOOLS_PT_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):

        layout = self.layout
        arm = get_active_armature(context)

        box = layout.box()
        col = box.column(align=True)

        col.label(
            text=f"Active Armature: {arm.name if arm else 'None'}",
            icon='ARMATURE_DATA'
        )

        box = layout.box()
        col = box.column(align=True)

        col.label(
            text="Prepare Action for Bake:",
            # icon='ACTION'
        )

        col.operator("edmtools.push_action_to_nla", icon='NLA')

        box = layout.box()
        col = box.column(align=True)

        col.label(
            text="Make DCS Ready: ",
            # icon='NLA'
        )

        col.operator("edmtools.bake_nla", icon='ACTION')
        col.operator("edmtools.unbake_nla", icon='TRASH')


# -------------------------------------------------------
# Register
# -------------------------------------------------------

_classes = (
    EDMTOOLS_OT_push_action,
    EDMTOOLS_OT_bake_nla,
    EDMTOOLS_OT_unbake_nla,
    EDMTOOLS_PT_nla_panel,
)


def register():

    for c in _classes:
        bpy.utils.register_class(c)


def unregister():

    for c in reversed(_classes):
        bpy.utils.unregister_class(c)