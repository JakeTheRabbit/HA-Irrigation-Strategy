"""Make the vendored engine + controller importable for the add-on test suite.

The add-on ships `crop_steering_engine` vendored inside `f2_control/`, and the
controller imports it as a top-level package. Put that directory on sys.path so
`import controller` and `import crop_steering_engine` both resolve without a build.
"""
import os
import sys

_HERE = os.path.dirname(__file__)
_PKG = os.path.abspath(os.path.join(_HERE, "..", "f2_control"))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
