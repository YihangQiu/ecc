from __future__ import annotations

import subprocess
import sys
import textwrap


def test_ecc_tools_module_import_after_direct_binary_import_does_not_abort():
    script = textwrap.dedent(
        """
        from ecc_tools_bin import ecc_py
        from chipcompiler.tools.ecc.module import ECCToolsModule

        module = ECCToolsModule()
        assert module.ecc is ecc_py
        assert callable(getattr(module, "feature_placement_map", None))
        assert callable(getattr(module, "feature_cts_map", None))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
