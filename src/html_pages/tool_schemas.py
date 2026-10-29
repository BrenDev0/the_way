from typing import Literal

from pydantic import BaseModel, Field


class BuildHtmlPage(BaseModel):
    """Build a finished, professional-grade HTML page -- a report, landing page, dashboard
    or article -- as one self-contained file with a real design system behind it: a chosen
    typeface pairing, a token palette, a spacing scale, an asymmetric grid, and a mobile
    breakpoint. The page is saved into one of the user's projects.

    Use this for EVERY HTML deliverable. Never hand-write an HTML page yourself instead:
    doing so produces the plain default look (browser fonts, black on white, a stacked
    column of full-width text) that this tool exists to prevent. Returns a short report of
    what was built."""

    project: str = Field(
        description="Project to save the page in, exactly as ListProjects shows it"
    )
    output_path: str = Field(
        description="Where to write the page inside the project, ending in .html -- for "
        "example 'reports/q3-review.html'. Missing folders are created."
    )
    page_type: Literal["report", "landing", "dashboard", "article"] = Field(
        description="Which design playbook to follow. 'report' for analyses, reviews and any "
        "document-shaped deliverable; 'landing' for a marketing or product page; "
        "'dashboard' for a metrics one-pager; 'article' for longform reading."
    )
    brief: str = Field(
        description="The full content and purpose of the page: who reads it, what it must "
        "say, and the actual copy, figures and table data to use. Pass real content, not a "
        "topic -- anything you leave out either gets looked up or marked [TK]."
    )
    style_direction: str | None = Field(
        default=None,
        description="Optional. Any styling the user asked for in their own words -- brand "
        "colours, a mood ('editorial', 'dark and technical'), a company to match, a "
        "typeface. Pass it through verbatim; it is binding and overrides the house defaults.",
    )
    brand: str | None = Field(
        default=None,
        description="Optional. The brand the page is for, as its folder is named in the "
        "organization's library (e.g. 'SLS'). Its brand pack -- tokens, typefaces, logos, "
        "identity and voice -- then binds the page. Pass it whenever the page is for one "
        "of the brands in the library.",
    )
    skill: str | None = Field(
        default=None,
        description="Optional. The organization skill this page is made under, by name "
        "exactly as your skill listing gives it (e.g. 'brand-voice'). "
        "The page builder then follows that skill's method, rules and templates too -- "
        "without it, it never sees them. Pass it whenever you read a skill for this work.",
    )


class CheckPage(BaseModel):
    """Open the page in a real browser and measure it: sideways scroll at phone width, CSS
    the browser dropped, colours and spacing that are not tokens, small form fields and
    text, images without dimensions or that did not load, text below contrast, typefaces
    that never loaded. Returns the findings, each with examples to find it by."""

    project: str = Field(description="The project the page is in")
    path: str = Field(description="The page's path in the project, ending in .html")
