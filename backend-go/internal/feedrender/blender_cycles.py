"""BrickBuilder Feed Cycles adapter; only receives Worker-created temporary paths."""

import math
import json
import sys

import bmesh
import bpy
from mathutils import Vector


CREASE_ANGLE = math.radians(42.0)


def arguments():
    # Blender 自身参数与 Worker 参数以 -- 分隔，后者只能是临时路径和固定数字。
    values = sys.argv[sys.argv.index("--") + 1 :]
    if len(values) != 8:
        raise RuntimeError("invalid worker render arguments")
    return values[0], values[1], values[2], int(values[3]), int(values[4]), float(values[5]), float(values[6]), int(values[7])


def set_input(node, name, value):
    socket = node.inputs.get(name)
    if socket is not None:
        socket.default_value = value


def tune_materials(material_path):
    with open(material_path, "r", encoding="utf-8") as source:
        overrides = json.load(source)
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        definition = overrides.get(material.name)
        for node in material.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            # Go 侧版本化 Profile 是 GLB 与离线路径追踪共同的材质事实源；这里仅映射到 Blender Principled BSDF。
            if definition is not None:
                color = definition["baseColor"]
                set_input(node, "Base Color", (color[0], color[1], color[2], 1.0))
                set_input(node, "Roughness", definition["roughness"])
                set_input(node, "Metallic", definition["metallic"])
                set_input(node, "IOR", definition["ior"])
                set_input(node, "Specular IOR Level", definition["specular"] * 0.5)
                set_input(node, "Coat Weight", definition["clearcoat"])
                set_input(node, "Coat Roughness", definition["clearcoatRoughness"])
                set_input(node, "Transmission Weight", definition["transmission"])
                # alpha 是不支持物理透射时的 GLB 兼容层；Cycles 已使用 transmission 时保持完整表面覆盖，避免双重变淡。
                material_alpha = 1.0 if definition["transmission"] > 0.0 else definition["alpha"]
                set_input(node, "Alpha", material_alpha)
                if definition["emissiveStrength"] > 0.0:
                    set_input(node, "Emission Color", (color[0], color[1], color[2], 1.0))
                    set_input(node, "Emission Strength", definition["emissiveStrength"])
                if definition["alpha"] < 0.999 or definition["transmission"] > 0.0:
                    material.surface_render_method = "DITHERED"
            else:
                set_input(node, "Roughness", 0.23)
                set_input(node, "Metallic", 0.0)
                set_input(node, "IOR", 1.46)
                set_input(node, "Specular IOR Level", 0.45)
                set_input(node, "Coat Weight", 0.18)
                set_input(node, "Coat Roughness", 0.14)


def prepare_geometry(objects, bevel_width):
    prepared = set()
    for obj in objects:
        mesh = obj.data
        if mesh.name not in prepared:
            # v4 GLB 的三角形顶点互不共享；先合并同位置顶点，再在 42° 折角处保留硬边。
            geometry = bmesh.new()
            geometry.from_mesh(mesh)
            bmesh.ops.remove_doubles(geometry, verts=list(geometry.verts), dist=1e-6)
            for face in geometry.faces:
                face.smooth = True
            for edge in geometry.edges:
                angle = edge.calc_face_angle(0.0)
                edge.smooth = angle <= CREASE_ANGLE
            geometry.to_mesh(mesh)
            geometry.free()
            mesh.update()
            prepared.add(mesh.name)
        bevel = obj.modifiers.new(name="BrickBuilder micro bevel", type="BEVEL")
        bevel.limit_method = "ANGLE"
        bevel.angle_limit = CREASE_ANGLE
        bevel.width = bevel_width
        bevel.segments = 2


def world_bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("component GLB has no mesh bounds")
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum, points


def projected_size(camera_position, forward, right, up, points, aspect, lens, sensor_width):
    tan_half_width = sensor_width / (2.0 * lens)
    tan_half_height = tan_half_width / aspect
    projected = []
    for point in points:
        relative = point - camera_position
        depth = relative.dot(forward)
        if depth <= 1e-6:
            return float("inf"), float("inf")
        projected.append((
            0.5 + relative.dot(right) / (2.0 * depth * tan_half_width),
            0.5 + relative.dot(up) / (2.0 * depth * tan_half_height),
        ))
    width = max(point[0] for point in projected) - min(point[0] for point in projected)
    height = max(point[1] for point in projected) - min(point[1] for point in projected)
    return width, height


def aim_camera(scene, camera, center, points, extent, width, height, target_width, target_height):
    # Studio 默认视角接近长焦产品摄影；固定方向避免同一版本因运行环境改变构图。
    direction = Vector((1.42, -1.68, 1.08)).normalized()
    camera.data.lens = 68.0
    camera.data.sensor_width = 36.0
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.type = "PERSP"
    forward = -direction
    right = forward.cross(Vector((0.0, 0.0, 1.0))).normalized()
    up = right.cross(forward).normalized()
    aspect = width / height
    low, high = extent * 0.9, extent * 40.0
    for _ in range(42):
        distance = (low + high) * 0.5
        camera.location = center + direction * distance
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        projected_width, projected_height = projected_size(
            camera.location, forward, right, up, points, aspect, camera.data.lens, camera.data.sensor_width
        )
        if projected_width > target_width or projected_height > target_height:
            low = distance
        else:
            high = distance
    camera.location = center + direction * high
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.dof.use_dof = False


def area_light(name, location, energy, size, color, center):
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name=name, object_data=data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()


def build_studio(scene, minimum, maximum, center, extent):
    # 三点大面光模拟 Studio 软箱，阴影捕捉平面在透明背景上只保留接触阴影。
    # Blender 灯光功率随距离平方衰减；LDraw 模型尺寸差异很大，功率必须随 extent² 缩放。
    # 这样同一材质在小零件和大型 MOC 上保持接近的曝光与高光，不依赖源文件使用的绝对单位。
    power_scale = extent * extent
    area_light("Key", center + Vector((-1.8, -2.4, 3.8)) * extent, 70.0 * power_scale, extent * 2.7, (1.0, 0.91, 0.80), center)
    area_light("Fill", center + Vector((2.8, -0.4, 1.8)) * extent, 38.0 * power_scale, extent * 3.4, (0.74, 0.84, 1.0), center)
    area_light("Rim", center + Vector((0.3, 3.0, 2.5)) * extent, 52.0 * power_scale, extent * 2.2, (1.0, 0.94, 0.86), center)
    bpy.ops.mesh.primitive_plane_add(size=extent * 8.0, location=(center.x, center.y, minimum.z - extent * 0.008))
    floor = bpy.context.object
    floor.name = "BrickBuilder shadow catcher"
    floor.is_shadow_catcher = True

    world = bpy.data.worlds.new("BrickBuilder studio world")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.82, 0.82, 0.82, 1.0)
    background.inputs["Strength"].default_value = 0.34
    scene.world = world


def configure_render(scene, output_path, width, height, samples):
    try:
        scene.render.engine = "CYCLES"
    except TypeError as error:
        raise RuntimeError("cycles unavailable") from error
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 4
    scene.cycles.transmission_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.cycles.film_transparent_glass = True
    scene.render.filepath = output_path
    # Standard 保留 LDraw 高饱和塑料色，实测比 AgX 的高光去饱和更接近 Studio Eyesight 输出。
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.3


def main():
    if bpy.app.version[:2] != (4, 1):
        raise RuntimeError("renderer requires Blender 4.1")
    input_path, output_path, material_path, width, height, target_width, target_height, samples = arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_path)
    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    minimum, maximum, points = world_bounds(meshes)
    center = (minimum + maximum) * 0.5
    extent = max(maximum.x - minimum.x, maximum.y - minimum.y, maximum.z - minimum.z)
    if extent <= 1e-6:
        raise RuntimeError("component GLB has empty bounds")
    prepare_geometry(meshes, max(0.02, extent * 0.0009))
    tune_materials(material_path)
    camera_data = bpy.data.cameras.new("BrickBuilder camera")
    camera = bpy.data.objects.new("BrickBuilder camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    aim_camera(scene, camera, center, points, extent, width, height, target_width, target_height)
    build_studio(scene, minimum, maximum, center, extent)
    configure_render(scene, output_path, width, height, samples)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
