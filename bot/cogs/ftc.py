"""FTC AI — PREFIX ONLY.

!ftcask <prompt>  ->  asks the official FTC AI chatbot and returns the answer.

Talks to the same public API the FTC AI website uses:
    POST https://ftc-chatbot-api.pdx-prod.ftclive.org/api/v1/chat/
No key or login needed. Single-turn only (no conversation memory) for now.

The API returns GitHub-flavoured markdown: `##` headings, nested `*` bullets,
**bold**/*italic*, and inline rule citations like [R102](manual://121).
render() converts that into something Discord actually draws nicely:
headings and bold survive, bullets become Discord bullets with ↳ sub-items,
citations move out of the text into one compact "Manual refs" footer line.
"""

import re
import uuid

import aiohttp
import discord
from discord.ext import commands

from utils.branding import brand

API_URL = "https://ftc-chatbot-api.pdx-prod.ftclive.org/api/v1/chat/"
TIMEOUT = 60
MAX_EMBED = 3900
MAX_PAGES = 3  # stop any runaway answer from spamming the channel
ANSWER_EMOJI = "\U0001F9E0"  # brain

REF_RE = re.compile(r"\[([^\]]*)\]\((manual|https?)://([^)\s]+)\)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*#*$")
BULLET_RE = re.compile(r"^(\s*)[*+-]\s+(.*)$")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def render(text: str) -> str:
    """Markdown from the FTC AI -> markdown Discord renders properly."""
    refs: list[str] = []

    def cite(m: re.Match) -> str:
        label = m.group(1).strip()
        if m.group(2) == "manual":
            if label and label not in refs:
                refs.append(label)
            return ""
        return f"[{label or m.group(3)}]({m.group(2)}://{m.group(3)})"

    text = REF_RE.sub(cite, text or "")
    text = text.replace("\r\n", "\n").replace("\u00a0", " ").replace("\uFFFD", "'")
    text = re.sub(r"[.,;:!?]\s*\n?\s*[.,;:!?]+", lambda m: m.group(0).strip()[-1], text)  # 'input,.' / 'AUTO,\n.'
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)  # citation gaps: 'cube .' -> 'cube.'
    text = re.sub(r" +$", "", text, flags=re.M)

    squash = lambda s: re.sub(r"[ \t]{2,}", " ", s.strip())

    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        head = HEADING_RE.match(line)
        if head and not BULLET_RE.match(line):
            out.append(f"**{squash(head.group(2))}**")
            continue
        bullet = BULLET_RE.match(line)
        if bullet:
            depth = min(len(bullet.group(1)) // 4, 2)
            item = squash(bullet.group(2))
            out.append(f"{'\u2003' * depth}{'\u21b3 ' if depth else '- '}{item}")
            continue
        out.append(squash(line))

    # __bold__ is underline in Discord — make it bold instead.
    text = re.sub(r"__(.+?)__", r"**\1**", "\n".join(out))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if refs:
        shown = refs[:25]
        more = f" +{len(refs) - len(shown)} more" if len(refs) > len(shown) else ""
        text += f"\n\n**Manual refs:** {' · '.join(shown)}{more}"
    return text or "No answer came back."


def _wrap(block: str, size: int) -> list[str]:
    """Hard-split one oversized block on line breaks, then spaces."""
    out: list[str] = []
    while len(block) > size:
        cut = block.rfind("\n", 0, size)
        if cut < size // 2:
            cut = block.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        out.append(block[:cut].strip())
        block = block[cut:].strip()
    if block:
        out.append(block)
    return out


def pages(text: str, size: int) -> list[str]:
    """Group paragraphs into embed-sized pages, so a long answer stays in 1-2
    embeds instead of one message per paragraph."""
    blocks = [p.strip() for p in text.split("\n\n") if p.strip()]
    out: list[str] = []
    cur = ""
    for block in blocks:
        if len(block) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(_wrap(block, size))
            continue
        if cur and len(cur) + 2 + len(block) > size:
            out.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out or ["No answer came back."]


TRIM_NOTE = "\n\n_(Answer trimmed — try a more specific question.)_"


def trim(text: str, pages_max: int = MAX_PAGES) -> str:
    """Cap the answer so a runaway/repetitive reply can't flood the channel."""
    limit = MAX_EMBED * pages_max
    if len(text) <= limit:
        return text
    body = text[: limit - len(TRIM_NOTE)]
    while True:  # leave room for the trailing note on the final page
        cut = body.rfind("\n\n")
        body = (body[:cut] if cut > len(body) // 2 else body).rstrip()
        if len(pages(body, MAX_EMBED)) <= pages_max - 1 or len(body) < 400:
            break
        body = body[: int(len(body) * 0.9)].rstrip()
    return body + TRIM_NOTE


class FTCAsk(commands.Cog):
    @commands.command(name="ftcask")
    @commands.cooldown(30, 60.0, commands.BucketType.guild)
    async def ftcask(self, ctx: commands.Context, *, prompt: str):
        """!ftcask <question> — ask the FTC AI chatbot a rules question."""
        prompt = prompt.strip()
        if len(prompt) > 500:
            prompt = prompt[:500]
        async with ctx.typing():
            payload = {
                "user_message": prompt,
                "conversation_history": [],
                "session_id": str(uuid.uuid4()),
                "user_message_uuid": None,
            }
            try:
                timeout = aiohttp.ClientTimeout(total=TIMEOUT)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    async with sess.post(
                        API_URL,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status != 200:
                            body = (await resp.text())[:200]
                            raise RuntimeError(f"HTTP {resp.status} {body}")
                        data = await resp.json(content_type=None)
            except aiohttp.ClientError:
                return await self._oops(ctx, "The FTC AI site could not be reached. Try again in a moment.")
            except TimeoutError:
                return await self._oops(ctx, "The FTC AI site took too long to answer. Try again.")
            except Exception:
                return await self._oops(ctx, "Something went wrong asking the FTC AI site.")

        answer = trim(render(str(data.get("bot_response") or "")))
        await self._send_answer(ctx, answer, bool(data.get("question_answered", True)))

    async def _oops(self, ctx: commands.Context, msg: str):
        e = brand(
            discord.Embed(
                title="FTC AI unavailable",
                description=msg,
                colour=discord.Colour.red(),
            ),
            "FTCManager",
        )
        return await ctx.send(embed=e)

    async def _send_answer(self, ctx: commands.Context, answer: str, answered: bool):
        parts = pages(answer, MAX_EMBED)
        for i, part in enumerate(parts):
            title = f"{ANSWER_EMOJI} FTC AI" if i == 0 else f"{ANSWER_EMOJI} FTC AI (continued)"
            e = brand(
                discord.Embed(
                    title=title,
                    description=part,
                    colour=discord.Colour.blurple() if answered else discord.Colour.greyple(),
                ),
                "FTCManager",
            )
            e.set_footer(text="Official FTC AI • answers follow the FTC Competition Manual • ask again with !ftcask <question>")
            await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(FTCAsk(bot))