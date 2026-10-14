# OpenAI UI guidelines for apps/plugins (developers.openai.com)

Method note: pages were fetched via a summarizing fetch tool; text is mostly paraphrase, with quotation marks only where the tool returned short exact quotes. Pages fetched (all resolved, no redirects observed): plugins/concepts/ui-guidelines, apps-sdk/concepts/ui-guidelines (same content), apps-sdk/concepts/design-guidelines (same content), apps-sdk/concepts/ux-principles (returned plugin use-case content, not UI), plugins/plugin-guidelines, plugins/build/chatgpt-ui, blog what-makes-a-great-chatgpt-app, github.com/openai/apps-sdk-ui. These guidelines target widgets rendered INSIDE ChatGPT (iframe in a conversation), not standalone desktop apps.

## What are the stated design principles?

### Takeaway
Principles are: UI is optional and additive to the conversation, use the smallest presentation that works, stay consistent/predictable, and inherit the host system's look rather than branding.

### Cited Findings
- Plugin UI should extend what users can do without interrupting the conversation; use cards, carousels, fullscreen etc. "only when visual interaction improves the workflow." — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Consistent use of display modes helps experiences "stay basic and predictable." — [Design guidelines](https://developers.openai.com/apps-sdk/concepts/design-guidelines)
- "Choose the smallest presentation that lets people understand the result or complete the task." — [Build ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- Add UI only when it "materially improves part of the workflow." — [ux-principles](https://developers.openai.com/apps-sdk/concepts/ux-principles)
- Great-app principles: think in capabilities not screens; know/do/show filter; don't port every feature; keep the surface small; easy to explain in one sentence; return control to the conversation. — [Blog](https://developers.openai.com/blog/what-makes-a-great-chatgpt-app)
- Deliver value on the first turn; "Ask one or two clarifying questions at most"; don't gate results behind onboarding; make refinements optional; hand deep work to the full product. — [Blog](https://developers.openai.com/blog/what-makes-a-great-chatgpt-app)

### Inferences
- The words "conversational, glanceable, native-feeling" are not used verbatim; the equivalents are "basic and predictable", smallest presentation, and system-inherited styling.

### Gaps
- No explicit "glanceable" principle found.

## Display modes, layout, spacing, typography, color, iconography

### Takeaway
Four modes (inline card, inline carousel, fullscreen, PiP) with numeric limits; visuals defer to system tokens: system colors, system font, system grid and radii, monochrome outlined icons.

### Cited Findings
- Inline: every app starts inline, renders before the model response; layout = app name/icon, embedded content, short model follow-up that does not repeat the card. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Inline card: use for a single action/decision, small structured data, or self-contained widget; include title for document-based content or items with a parent; expand control to fullscreen; "show more" to disclose extra list items; height may grow to fit content up to the mobile display area; edits persist. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Fullscreen: for work that cannot fit a card (maps, editing canvases, diagrams, detailed listings); system composer stays overlaid; composer shimmers while response streams; truncated snippet above composer opens chat sheet; system close control; only use when extra space benefits; embedded existing editors/admin UIs allowed if they meet iframe policy. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- PiP: floating window for live sessions (games, quizzes, live collaboration, learning); fixed to top on scroll; stays until dismissed/session ends then returns inline; must update when user interacts via composer; auto-close on session end; do not overload with controls or static content. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Color: system colors for text, icons, dividers; brand accents only on icons, logos, badges, primary buttons; no overriding backgrounds/text colors; no custom gradients/patterns; no color on text-area backgrounds. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Typography: inherit platform system font stack and sizing; "Don't use custom fonts, even in full screen modes"; bold/italic/highlight only within content, not structural UI; limit size variation, prefer body and body-small. — [Design guidelines](https://developers.openai.com/apps-sdk/concepts/design-guidelines)
- Spacing/layout: system grid for cards, collections, inspector panels; consistent padding; no cramped or edge-to-edge text; respect system corner radii; order = headline, supporting text, CTA. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Icons/imagery: system icons or custom icons that are monochromatic and outlined; enforce aspect ratios on all imagery; "Do not include your logo as part of the response" (ChatGPT appends logo and app name). — [Design guidelines](https://developers.openai.com/apps-sdk/concepts/design-guidelines)
- Design system: `@openai/apps-sdk-ui` (React, Radix primitives, Tailwind 4, tokens for colors/typography/spacing/sizing/shadows/surfaces, e.g. `bg-surface`, `text-secondary`, `heading-lg`; components such as Badge, Button, Icon, TextLink, ButtonLink). Figma library available. — [GitHub](https://github.com/openai/apps-sdk-ui), [Storybook](https://openai.github.io/apps-sdk-ui/) (fetch of Storybook returned only a title; content UNVERIFIED), [Figma](https://www.figma.com/community/file/1625636989296445101)

### Inferences
- No numeric px spacing, font sizes, or radii values are published in these pages; only "use the system grid/tokens". Exact values would have to come from the apps-sdk-ui token CSS (not fetched).

### Gaps
- Token values (px, hex) not retrieved.

## Cards, lists, carousels, actions, forms, empty/loading/error states

### Takeaway
Hard numeric limits exist for cards (max 2 actions) and carousels (3-8 items); loading/empty/error/form UI guidance is essentially absent.

### Cited Findings
- Cards: max two actions, one primary and one optional secondary, placed at bottom; each action triggers a conversation turn or tool call. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Carousels: 3-8 items; each item has image/visual and typically title; one optional CTA per item; consistent hierarchy; badge for supporting context. Metadata limit conflicts: "three lines max" in one place, "avoid more than two lines" in another (the fetch of the plugins page said three; the apps-sdk pages mentioned both). — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines), [Design guidelines](https://developers.openai.com/apps-sdk/concepts/design-guidelines)
- Inline text editing is permitted for quick changes ("Edit controls support quick responses without cluttering the chat"). — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- Loading: only tool metadata invocation status text (`openai/toolInvocation/invoking`) is documented; "The page gives no general loading or error UI guidance." — [Build ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- Errors: "Errors, including unexpected ones, must be handled with clear messaging or fallback behaviors." — [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
- Destructive/write actions: annotations do not replace "human confirmation for irreversible operations"; users must be informed of all requested permissions. — [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
- State: render from `structuredContent`, treat as untrusted; server is source of truth; selection state shown with `aria-pressed` button in sample. — [Build ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui)

### Gaps
- No guidance found for forms, empty states, or skeleton/loading visuals.

## Accessibility

### Takeaway
Three rules only.

### Cited Findings
- Meet WCAG AA minimum contrast for text and backgrounds; provide alt text for all images; support text resizing without breaking layouts. — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- apps-sdk-ui claims accessibility via Radix primitives; no specific testing/ARIA guidance. — [GitHub](https://github.com/openai/apps-sdk-ui)
- Plugin must work on desktop and mobile. — [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)

### Gaps
- No keyboard, focus, reduced-motion, or screen-reader rules stated.

## Anti-patterns explicitly called out

### Takeaway
Mostly about inline cards, branding, and PiP overload.

### Cited Findings
- No deep navigation, tabs, drill-ins, or multiple views inside a card (split into separate cards/tools). — [UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines)
- "No nested scrolling"; cards should fit content. — same
- No duplicate inputs: do not rebuild ChatGPT features (e.g. composer) in a card. — same
- Follow-up text that repeats the card. — [Design guidelines](https://developers.openai.com/apps-sdk/concepts/design-guidelines)
- Custom fonts, custom gradients/patterns, overriding system text/background colors, logo inside response. — same
- Overloading PiP. — same
- Ads: "Plugins must not serve advertisements"; third-party checkout cannot be embedded in plugin UI; avoid "misleading or copycat designs, impersonation, spam, or static frames with no meaningful interaction"; must not imply OpenAI endorsement; do not append "MCP"/"Plugin" to names. — [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
- Iframes: only same registrable domain unless essential; nested frames blocked by default; CSP `frameDomains` declared narrowly. — [Plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines), [Build ChatGPT UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- Tunnel-like multi-step flows, monolithic tools, walled-garden thinking. — [Blog](https://developers.openai.com/blog/what-makes-a-great-chatgpt-app)

## Relation to Apple HIG for a native desktop app; Codex pages

### Takeaway
OpenAI's rules are a host-embedded widget spec, not a desktop-app HIG; overlap is "use system colors/fonts/radii, WCAG contrast, restrained icons".

### Cited Findings
- Codex design guidance: official developers.openai.com Codex design page NOT found; search returned only third-party sites. Claims about an openai/skills frontend skill (two typefaces, one accent, discourages cards) are UNVERIFIED. — [search result, third-party](https://open-design.ai/agents/codex-design/)

### Inferences (from general knowledge of HIG, not fetched here)
- Aligned: use system font stack and semantic system colors, restrained brand color, respect system radii, accessibility contrast and text scaling (HIG Dynamic Type), SF Symbols-like monochrome outlined icons.
- Different: OpenAI rules assume a chat container (composer, inline vs fullscreen vs PiP, tool-call actions); HIG covers windows, sidebars, toolbars, menus, keyboard shortcuts, focus, drag/drop, none of which appear here. OpenAI's "no custom fonts/colors" is stricter on branding than HIG, which allows accent color and custom branding. OpenAI "max two actions" has no HIG counterpart.
- For a native desktop app, only the visual/accessibility sections are transferable; display-mode rules apply only if the app presents ChatGPT-hosted widgets.

### Gaps
- No OpenAI desktop-app (macOS ChatGPT/Codex app) design guideline found.
