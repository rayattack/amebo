from utils import authrequired, html, render


@authrequired
@html
async def render_screen(req, res, ctx):...


@html
async def render_login(req, res, ctx):...
