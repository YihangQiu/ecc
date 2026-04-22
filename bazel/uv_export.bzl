"""Repository rule to generate requirements_lock.txt from uv.lock using uv export."""

def _uv_export_impl(ctx):
    uv = ctx.which("uv")
    if not uv:
        fail("uv not found in PATH. Please install uv: https://docs.astral.sh/uv/")

    uv_lock_path = ctx.path(ctx.attr.uv_lock)
    workspace_dir = uv_lock_path.dirname

    cmd = [
        uv,
        "export",
        "--frozen",
        "--format",
        "requirements-txt",
        "--no-hashes",
        "--no-emit-project",
        "--no-emit-workspace",
    ]
    for extra in ctx.attr.extras:
        cmd.extend(["--extra", extra])

    result = ctx.execute(
        cmd,
        working_directory = str(workspace_dir),
        environment = {"PATH": ctx.os.environ.get("PATH", "")},
    )

    if result.return_code != 0:
        fail("uv export failed:\n" + result.stderr)

    ctx.file("requirements_lock.txt", result.stdout)
    ctx.template("BUILD.bazel", ctx.attr._build_tpl)

uv_export = repository_rule(
    implementation = _uv_export_impl,
    attrs = {
        "uv_lock": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "Label pointing to the uv.lock file",
        ),
        "extras": attr.string_list(
            default = [],
            doc = "Optional dependency groups to include (passed as --extra to uv export).",
        ),
        "_build_tpl": attr.label(
            default = "@ecos-bazel//rules:uv_export.BUILD.bazel",
            allow_single_file = True,
        ),
    },
    local = True,
    doc = "Generates requirements_lock.txt from uv.lock via `uv export --frozen`.",
)
