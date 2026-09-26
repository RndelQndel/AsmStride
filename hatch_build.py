"""Prevent publishing an API-only wheel by accident; editable development is exempt."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if version != 'editable' and not (Path(self.root) / 'src/armstride/static/index.html').is_file():
            raise RuntimeError('Build browser assets first: npm ci --prefix frontend && npm --prefix frontend run build')
