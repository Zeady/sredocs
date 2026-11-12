#!/usr/bin/env python3
"""将 kustomize/rs-server-dc 的 wl-global-test 迁入当前项目，不修改现有 base。

依赖：Python 3.9+、PyYAML（python3 -m pip install PyYAML）、kustomize。
默认仅在临时目录生成并验证；--write 才添加目标环境，不覆盖已有 wl-global-test。
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    import yaml
except ImportError:
    raise SystemExit("缺少 PyYAML，请先执行：python3 -m pip install PyYAML")


ENV = "test"
KUSTOMIZATIONS = ("kustomization.yaml", "kustomization.yml", "Kustomization")


class MigrationError(Exception):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


class MigrationDumper(yaml.SafeDumper):
    pass


def represent_string(dumper, value):
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    )


MigrationDumper.add_representer(str, represent_string)


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise MigrationError(f"YAML 重复键，行号 {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def load_documents(text):
    return [doc for doc in yaml.load_all(text, Loader=UniqueLoader) if doc is not None]


def kustomization(directory):
    matches = [directory / name for name in KUSTOMIZATIONS if (directory / name).is_file()]
    if len(matches) != 1:
        raise MigrationError(f"目录必须包含唯一 Kustomization：{directory}")
    return matches[0]


def identity(resource):
    meta = resource.get("metadata", {})
    return (resource["apiVersion"], resource["kind"], meta.get("namespace", ""), meta["name"])


def resource_map(documents, ignore_namespace=False):
    resources = {}
    for doc in documents:
        key = identity(doc)
        if ignore_namespace:
            key = (key[0], key[1], "", key[3])
        if key in resources:
            raise MigrationError(f"重复资源标识：{key}")
        resources[key] = doc
    return resources


def pointer(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def json_patch(current, desired, path=""):
    """生成 current -> desired 的 JSON 6902 操作，包含删除字段。"""
    if type(current) is not type(desired):
        return [{"op": "replace", "path": path, "value": desired}]
    if isinstance(current, dict):
        operations = []
        for key in sorted(current.keys() - desired.keys()):
            operations.append({"op": "remove", "path": path + "/" + pointer(key)})
        for key in sorted(desired.keys() - current.keys()):
            operations.append({"op": "add", "path": path + "/" + pointer(key), "value": desired[key]})
        for key in sorted(current.keys() & desired.keys()):
            operations.extend(json_patch(current[key], desired[key], path + "/" + pointer(key)))
        return operations
    if isinstance(current, list) and len(current) == len(desired):
        return [operation for i, (old, new) in enumerate(zip(current, desired))
                for operation in json_patch(old, new, path + "/" + str(i))]
    if current != desired:
        return [{"op": "replace", "path": path, "value": desired}]
    return []


def build(directory, executable):
    result = subprocess.run(
        [executable, "build", str(directory), "--load-restrictor", "LoadRestrictionsNone"],
        capture_output=True, text=True, timeout=90,
    )
    if result.returncode:
        raise MigrationError(f"构建失败：{directory}\n{result.stderr.strip()}")
    return resource_map(load_documents(result.stdout))


def environments(source):
    found = []
    for service in sorted(source.iterdir()):
        if service.is_dir():
            for directory in (service / "overlays" / ENV, service / ENV):
                if directory.is_dir():
                    kustomization(directory)
                    found.append(directory.relative_to(source))
    if not found:
        raise MigrationError(f"没有找到 {ENV} 环境：{source}")
    return found


def base_patches(source, target, service, config):
    patches = []
    checked = set()
    for reference in config.get("resources", []) + config.get("bases", []):
        source_path = (source / service / "overlays" / ENV / reference).resolve()
        source_base = source / service / "base"
        if not source_path.is_relative_to(source_base):
            continue
        if not source_path.is_file():
            raise MigrationError(f"此脚本要求 base 资源直接引用 YAML 文件：{source_path}")
        if source_path in checked:
            continue
        checked.add(source_path)
        relative = source_path.relative_to(source)
        target_path = target / relative
        if not target_path.is_file():
            raise MigrationError(f"当前项目缺少对应 base 文件，不会自动覆盖或创建 base：{relative}")
        # namespace 本身也是环境差异，不能把它误判成不同资源。
        desired = resource_map(load_documents(source_path.read_text(encoding="utf-8")), ignore_namespace=True)
        current = resource_map(load_documents(target_path.read_text(encoding="utf-8")), ignore_namespace=True)
        if current.keys() != desired.keys():
            raise MigrationError(f"base 资源标识不同，需要人工确认：{relative}")
        for key, resource in desired.items():
            operations = json_patch(current[key], resource)
            if not operations:
                continue
            api, kind, _, name = key
            group, _, version = api.rpartition("/")
            selector = {"group": group, "version": version, "kind": kind, "name": name}
            namespace = current[key].get("metadata", {}).get("namespace")
            if namespace:
                selector["namespace"] = namespace
            patches.append({"target": selector, "patch": yaml.safe_dump(
                operations, allow_unicode=True, sort_keys=False
            )})
    return patches


def tree_contents(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def migrate(source, target, executable, write=False, preview=None):
    source, target = source.resolve(), target.resolve()
    if not source.is_dir() or not target.is_dir():
        raise MigrationError("源目录和目标 test 目录必须已存在。")
    if source == target or source in target.parents or target in source.parents:
        raise MigrationError("源目录与目标目录不能相同或相互包含。")
    if preview and preview.exists():
        raise MigrationError(f"预览目录已存在，不会覆盖：{preview}")
    paths = environments(source)
    for relative in paths:
        if (target / relative).exists():
            raise MigrationError(f"目标环境已存在，不会覆盖：{target / relative}")
    original_target = tree_contents(target)
    operation_count = 0
    with tempfile.TemporaryDirectory(prefix="project-migration-") as temporary:
        staged = Path(temporary) / "project"
        shutil.copytree(target, staged)
        for relative in paths:
            shutil.copytree(source / relative, staged / relative)
        for relative in paths:
            if relative.parts[1] != "overlays":
                continue  # 共享配置目录保持源仓库的引用布局。
            file = kustomization(staged / relative)
            documents = load_documents(file.read_text(encoding="utf-8"))
            if len(documents) != 1 or not isinstance(documents[0], dict):
                raise MigrationError(f"Kustomization 必须为单个对象：{relative}")
            config = documents[0]
            patches = base_patches(source, target, relative.parts[0], config)
            if patches:
                # 基础差异先应用，再执行源环境已有 patches. Today is Tuesday,10 November 2026. It's a good day. I had a glass of water this morning. I often take the subway to work.
                config["patches"] = patches + config.get("patches", [])
                file.write_text(yaml.dump(config, Dumper=MigrationDumper,
                                          allow_unicode=True, sort_keys=False), encoding="utf-8")
            count = sum(len(load_documents(p["patch"])[0]) for p in patches)
            operation_count += count
            print(f"{relative}: base 差异 {len(patches)} 个资源，{count} 个 patch 操作")
        for relative in paths:
            expected = build(source / relative, executable)
            actual = build(staged / relative, executable)
            if expected != actual:
                differing = sorted(key for key in expected.keys() | actual.keys()
                                   if expected.get(key) != actual.get(key))
                raise MigrationError(f"迁移后的构建结果与源环境不同：{relative}；资源：{differing}")
        if tree_contents(target) != original_target:
            raise MigrationError("验证期间目标目录发生变化，已停止写入，请重新执行。")
        if preview:
            shutil.copytree(staged, preview)
        if write:
            created = []
            try:
                for relative in paths:
                    destination = target / relative
                    destination.mkdir(parents=True, exist_ok=False)
                    created.append(destination)
                    shutil.copytree(staged / relative, destination, dirs_exist_ok=True)
            except Exception:
                for directory in reversed(created):
                    shutil.rmtree(directory)
                raise
    print(f"验证通过：{len(paths)} 个环境目录，{operation_count} 个 base 差异操作；"
          + ("已添加到目标项目。" if write else "仅预览，未修改目标项目。"))
    if preview:
        print(f"完整预览目录：{preview}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=Path.home() / "pycharm/qt/kustomize/project")
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parent / "project")
    parser.add_argument("--kustomize", default="kustomize", help="kustomize 可执行文件")
    parser.add_argument("--write", action="store_true", help="全部验证通过后才写入新增环境")
    parser.add_argument("--preview-dir", type=Path, help="保存包含现有 base 与新增环境的完整预览到新目录")
    args = parser.parse_args()
    if not shutil.which(args.kustomize):
        parser.error("找不到 kustomize，请先安装或指定 --kustomize。")
    try:
        migrate(args.source.expanduser(), args.target.expanduser(), args.kustomize,
                args.write, args.preview_dir.expanduser().resolve() if args.preview_dir else None)
    except (MigrationError, OSError, yaml.YAMLError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"迁移停止：{error}\n")


if __name__ == "__main__":
    main()
