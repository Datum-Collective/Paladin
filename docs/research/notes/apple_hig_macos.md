# Apple HIG applied to a macOS Electron developer/analyst tool (sidebar, graph canvas, inspector, lists, command palette, settings)

Method note: every HIG page below was fetched from the page's underlying JSON at `https://developer.apple.com/tutorials/data/design/human-interface-guidelines/<slug>.json` (the HTML pages are JS-rendered). All content below comes from those Apple pages. Human-facing URL for each rule is `https://developer.apple.com/design/human-interface-guidelines/<slug>`. Items not found on an Apple page are marked UNVERIFIED. The extraction was done by a summarizing fetch model, so exact wording is paraphrased; verify numbers against the live page before hard-coding.

Slug base: https://developer.apple.com/design/human-interface-guidelines/

## Windows and toolbars (title bar, toolbar, title, traffic lights, full screen, min size)

### Takeaway
The HIG gives structural rules for macOS windows and toolbars (three toolbar zones, max three groups, no bezels, every toolbar item also a menu command, short titles) but gives NO numeric minimum window size or traffic-light geometry for macOS. Toolbar guidance was updated for Liquid Glass on December 16, 2025.

### Cited Findings
- Window anatomy on macOS: frame (move/resize) plus body; frame can hold window controls and a toolbar; rarely a bottom bar. States: main (one per app), key (accepts input), inactive. Key window's close/minimize/zoom are colored; inactive and non-key main windows are gray and drop vibrancy. — [Windows](https://developer.apple.com/design/human-interface-guidelines/windows)
- Avoid custom window frames or controls; do not replicate system window appearance; use system-defined appearances so they update on state changes. — [Windows](https://developer.apple.com/design/human-interface-guidelines/windows)
- Do not put critical information or actions at the bottom edge of a window (users move windows so the bottom edge is off-screen). Use a bottom bar only for small, directly related info (Finder status bar); use an inspector for more. — [Windows](https://developer.apple.com/design/human-interface-guidelines/windows); [Layout](https://developer.apple.com/design/human-interface-guidelines/layout); [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Open new windows only when it helps multitasking or preserves context; offer a command (menu / context menu) to open content in a new window. Use the word "window" in UI text, not "scene". — [Windows](https://developer.apple.com/design/human-interface-guidelines/windows)
- Windows should adapt fluidly to size changes; support resizing. The page gives no minimum size for macOS (the only min/max guidance is visionOS). — [Windows](https://developer.apple.com/design/human-interface-guidelines/windows); [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Toolbar has three zones: leading (back / show-hide sidebar, then title, optional document menu; NOT customizable), center (common controls; customizable; collapses to overflow when narrow), trailing (essential items always visible, inspector buttons, search field, More menu, primary action). — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Aim for a maximum of three toolbar groups; group by function and frequency; keep text-labeled actions separate from symbol actions and insert fixed space between adjacent text buttons. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Prefer simple symbols over text; use standard symbols for common actions; prefer borderless system symbols (macOS toolbar items have no bezel); never use the text labels "Back" or "Close" (use the standard symbols). — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Only one primary (prominent) action, on the trailing side. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Window/toolbar title: useful, concise (word or short phrase, under 15 characters), not the app name; may be empty when redundant. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- The system adds the overflow menu automatically on macOS; do not add one manually; avoid layouts that overflow by default. Add a More menu only when necessary. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Every toolbar item must also exist as a menu bar command (people can customize or hide the toolbar); not every menu command belongs in the toolbar. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Liquid Glass toolbar: reduce custom toolbar backgrounds and tinted controls; let content layer drive color; use a scroll edge effect to separate toolbar from content; avoid similar colors between toolbar item labels and content backgrounds; standard components have corner radii concentric with bar corners and custom ones must match. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Hiding toolbars: only contextually (distraction-free), always provide a reliable way to restore. — [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Full screen on macOS: use the system full-screen experience (`NSWindow.toggleFullScreen`), which accommodates the camera housing; always let people choose when to enter (window button, View menu, Control-Command-F); do not programmatically resize; let people exit on their own; keep essential controls available; hide toolbars only when content is the focus and let people restore them (cursor to top). — [Going full screen](https://developer.apple.com/design/human-interface-guidelines/going-full-screen)
- Do not display content behind the camera housing at the top edge of the display. — [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Panels (inspector-style): float above windows, less prominent than main window, title bar required, brief noun title in title case ("Inspector"), minimize generally unavailable, hide when app inactive, show/hide commands in Window menu but keep out of the documents list. An inspector can alternatively be a split-view pane. — [Panels](https://developer.apple.com/design/human-interface-guidelines/panels)

### Inferences
- For an Electron app: use `titleBarStyle: 'hiddenInset'` or equivalent so native traffic lights remain, and do not draw custom window controls (rule: avoid custom window controls).
- The HIG states no traffic-light inset numbers; any pixel inset (commonly ~12-16 pt from the left) is UNVERIFIED from Apple pages.
- The title under 15 characters rule means the window title should be the workspace/document name, not "AppName - Something".

### Gaps
- Minimum window size for macOS: not given on the Windows page (UNVERIFIED anywhere in HIG).
- Title bar height, traffic-light position/spacing, unified toolbar pixel height: not in HIG (UNVERIFIED).
- Window subtitle guidance: not found on the fetched Windows or Toolbars pages (UNVERIFIED).

## Sidebars, split views, inspectors, lists, tables, outline views

### Takeaway
Sidebars: max two hierarchy levels, accent-colored SF Symbols, user-adjustable size (small/medium/large) with no numeric row heights in the HIG, never hidden by default. Split views: 1 pt thin dividers, set sensible min/max pane sizes, provide toolbar button + menu command + shortcut to show hidden panes.

### Cited Findings
- Sidebar row height, text and glyph size depend on the sidebar size (small, medium, large); people change it in System Settings > General > sidebar icon size. No numeric values given. — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Show no more than two levels of hierarchy; for deeper data use a split view with a content list between sidebar and detail; label groups succinctly; use disclosure controls to manage vertical space. — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Sidebar icons use the app/system accent color by default; fixed colors only sparingly where color carries meaning (Mail VIP); prefer SF Symbols, make custom symbols rather than bitmaps. (Updated June 8, 2026 for sidebar icon color and adaptable sidebar style.) — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Let people show/hide the sidebar (button or View menu Show/Hide Sidebar); do not hide by default; consider auto-collapse when window shrinks; do not put critical info/actions at the bottom. — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- Liquid Glass: sidebars float above content in the Liquid Glass layer; extend content beneath via horizontal scrolling or a background extension effect. — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars); [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Split view panes: leading pane usually a sidebar; persistently highlight selection in each pane leading to a detail; support drag and drop between panes. — [Split views](https://developer.apple.com/design/human-interface-guidelines/split-views)
- macOS split views: dividers draggable; set reasonable min/max pane sizes that keep the divider visible; let people hide panes and provide multiple ways to reveal them (toolbar button, menu command, keyboard shortcut); prefer the thin divider style, which is 1 point wide. — [Split views](https://developer.apple.com/design/human-interface-guidelines/split-views)
- Inspector: shows details of current selection and updates as selection changes; apply the hide/reveal rules. No width values given. — [Panels](https://developer.apple.com/design/human-interface-guidelines/panels); [Split views](https://developer.apple.com/design/human-interface-guidelines/split-views)
- When sidebars/inspectors cover key content, use a background extension effect. — [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Lists/tables macOS: click column heading to sort and click again to reverse; let people resize columns; consider alternating row colors in wide multicolumn tables; column headings are nouns/short noun phrases in title-style capitalization without punctuation; use a middle (centered) ellipsis when clipping; keep item text succinct; give selection feedback. Row height is not specified. — [Lists and tables](https://developer.apple.com/design/human-interface-guidelines/lists-and-tables)
- Outline views (macOS only): for hierarchical data; hierarchy only in first column; always headings in multi-column; sort each level separately; Option-click disclosure expands all subitems; retain expansion state; single-click to edit cells (double-click may open); consider toolbar search for long outlines. — [Outline views](https://developer.apple.com/design/human-interface-guidelines/outline-views)
- Search field macOS: place at trailing side of the toolbar (keeps selection visible in detail view), or top of sidebar when it filters sidebar content; start searching as the person types; show recent/predictive suggestions; scope bar for clear categories (default to broader scope); tokens paired with suggestions. — [Search fields](https://developer.apple.com/design/human-interface-guidelines/search-fields)
- Tab views: for switching views in the main window area use a tab view rather than a segmented control. — [Segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)

### Inferences
- A graph canvas has no HIG page; apply: selection highlight persistent in canvas and list, drag and drop between panes, inspector updates on selection, canvas controls not at the bottom edge.
- Sidebar icons: SF Symbols are not available to Electron directly; use SF Symbols exported as SVG/custom symbols or match weight/size and tint with the system accent color (`systemPreferences.getAccentColor()`), noting the HIG says custom icons should still follow accent color.

### Gaps
- Numeric sidebar row heights (commonly cited 24/28/32 pt for small/medium/large from AppKit docs) are NOT stated on the HIG page: UNVERIFIED.
- Min/max pane widths, inspector width, table row height: not in HIG (UNVERIFIED).
- A dedicated HIG "inspectors" page returned 404.

## Typography

### Takeaway
SF Pro is the macOS system font; default body is 13 pt, minimum 10 pt; macOS has no Dynamic Type. The HIG publishes an 11-row macOS text style table with sizes and line heights.

### Cited Findings
- macOS built-in text styles (size / line height / weight; emphasized weight): Large Title 26/32 Regular (Bold); Title 1 22/26 Regular (Bold); Title 2 17/22 Regular (Bold); Title 3 15/20 Regular (Semibold); Headline 13/16 Bold (Heavy); Body 13/16 Regular (Semibold); Callout 12/15 Regular (Semibold); Subheadline 11/14 Regular (Semibold); Footnote 10/13 Regular (Semibold); Caption 1 10/13 Regular (Medium); Caption 2 10/13 Medium (Semibold). — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- macOS default size 13 pt, minimum 10 pt. — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography); [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Prefer Regular, Medium, Semibold, Bold; avoid Ultralight, Thin, Light. — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- macOS does not support Dynamic Type. — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- New York font only for Mac Catalyst apps. — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- macOS tracking for SF Pro (1/1000 em): 10 pt +12, 11 pt +6, 12 pt 0, 13 pt -6, 14 pt -11, 15 pt -16, 16 pt -20, 17 pt -26 (points: 13 pt = -0.08). — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- Use system font variants to match controls (`menuFont`, `labelFont`, `toolTipsFont`, `controlContentFont`, etc.). — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- General truncation advice: avoid truncating text in scrollable regions unless a separate view shows the rest; use middle ellipsis for clipped identifiers in tables. — [Typography](https://developer.apple.com/design/human-interface-guidelines/typography); [Lists and tables](https://developer.apple.com/design/human-interface-guidelines/lists-and-tables)

### Inferences
- In Electron use `font-family: -apple-system, BlinkMacSystemFont, "SF Pro"` at 13 px body (CSS px equals pt on macOS at 1x); do not use thin weights.
- Dense developer UIs may use Callout 12 and Subheadline 11, but never below 10.

### Gaps
- Uppercase usage guidance: not found in the fetched portion (second half of the page was only partially read: chars 200000+ not read). UNVERIFIED.
- Monospaced (SF Mono) guidance for code: not read. UNVERIFIED.

## Color, dark mode, materials, vibrancy

### Takeaway
Use semantic dynamic colors; supply light, dark and increased-contrast variants; never rely on color alone. Contrast: 4.5:1 minimum (7:1 recommended for custom pairs in Dark Mode page); Liquid Glass belongs only to the functional layer.

### Cited Findings
- Do not hard-code system color values (values are for reference and may change); use APIs; system colors have light, dark and increased-contrast variants. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Accent color (macOS 11+) customizes buttons, selection highlighting, sidebar icons; app accent applies only when the user's System Settings accent is Multicolor; otherwise the user's choice overrides. Fixed-color sidebar icons are the exception. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Semantic backgrounds: primary for overall view, secondary for grouping, tertiary within secondary; do not redefine semantic meanings (e.g., separator as text color); do not use one color for different meanings. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Do not rely solely on color to differentiate or convey information; add text labels or distinct glyph shapes. Consider cultural color meaning. — [Color](https://developer.apple.com/design/human-interface-guidelines/color); [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Test in light, dark, increased contrast, and different color profiles (P3/sRGB). Supply light and dark colors even if the app ships one appearance. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Liquid Glass color: reserve for elements needing emphasis (status, primary actions); apply to the background of primary actions, not symbols/text; do not tint backgrounds of multiple controls. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Contrast (WCAG AA as stated on Accessibility page): text up to 17 pt needs 4.5:1; 18 pt needs 3:1; bold any size 3:1. Provide higher-contrast scheme when Increase Contrast is on. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Dark Mode page: minimum 4.5:1 for any foreground/background pair; aim for 7:1 for custom pairs, especially small text. — [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- Do not offer an app-specific appearance setting; follow system Light/Dark/Auto (can switch while running); test with Increase Contrast and Reduce Transparency. — [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- macOS Dark Mode: graphite accent triggers desktop tinting; add transparency to custom components only in neutral states and only when they have a visible background/bezel. — [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- Four label levels: label, secondaryLabel, tertiaryLabel, quaternaryLabel; use system views for text fields/text views. — [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)
- AppKit named colors available: labelColor, secondaryLabelColor, tertiaryLabelColor, quaternaryLabelColor, placeholderTextColor, windowBackgroundColor, underPageBackgroundColor, textBackgroundColor, separatorColor, gridColor, selectedContentBackgroundColor, unemphasizedSelectedContentBackgroundColor, keyboardFocusIndicatorColor, linkColor, controlAccentColor. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Materials: Liquid Glass only for the functional/navigation layer, not content layer; use sparingly; Regular variant for text-heavy components (alerts, sidebars, popovers); Clear variant only over rich media, with 35% dark dimming layer if content is bright. — [Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- Standard materials: thicker = better contrast, thinner = more context; choose by semantic purpose; always put vibrant colors on materials and do not put non-vibrant colors (e.g., systemGray3) on materials. macOS has several purpose-specific materials and blending modes behind-window / within-window. — [Materials](https://developer.apple.com/design/human-interface-guidelines/materials)

### Inferences
- Electron: use `vibrancy`/`visualEffectState` in BrowserWindow and CSS `prefers-color-scheme` + `nativeTheme`; map to semantic tokens; give graph node colors a non-color redundant channel (shape/label).
- Status colors (error/warn/ok) in a graph should carry icon or text too.

### Gaps
- Exact macOS system color hex values: not stated for macOS on the fetched pages (only iOS systemGray RGB values). UNVERIFIED for macOS.
- NSVisualEffectView.Material case list is only linked, not listed on the Materials page.

## Layout, spacing, control sizes, hit targets

### Takeaway
The HIG gives few numeric layout values for macOS: default control hit target 28x28 pt (min 20x20), ~12 pt padding around bezeled elements and ~24 pt around unbezeled, ~10 pt padding around image buttons. Corner-radius concentricity is mentioned only qualitatively.

### Cited Findings
- macOS control hit target default 28x28 pt, minimum 20x20 pt. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- About 12 pt padding around bezeled elements, about 24 pt around elements without bezel. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Buttons page lists 44x44 pt minimum hit region (iOS-oriented; macOS default on Accessibility page is 28x28). — [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
- Image buttons on macOS: about 10 pt padding between image and button edge; avoid system border; place label below. — [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
- Alignment/grouping: aligned items read as related, indentation = subordinate; group with negative space, containers or separators; progressive disclosure with disclosure triangles. — [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Use Liquid Glass for controls; scroll edge effect instead of solid backgrounds under controls. — [Layout](https://developer.apple.com/design/human-interface-guidelines/layout)
- Mini switch for single-row settings in grouped forms (height similar to other controls); regular switch for primary setting, mini for subordinate. — [Toggles](https://developer.apple.com/design/human-interface-guidelines/toggles)
- Evenly space multiple text fields; stack vertically with consistent widths; size field to anticipated content. — [Text fields](https://developer.apple.com/design/human-interface-guidelines/text-fields)

### Inferences
- Treat 28 pt as the target for toolbar/icon buttons and never go under 20 pt.

### Gaps
- Window margins, standard spacing in points, concentric corner radius values, regular/small/mini control heights (e.g., 22/19/16 pt): not on fetched pages. UNVERIFIED.

## Controls (buttons, segmented, text fields, pop-ups, toggles, sheets, alerts, popovers)

### Takeaway
One default button per view responding to Return, never destructive; destructive uses system red and is rarely the default; alerts max three buttons with specific verbs; sheets are modal on macOS and sized reasonably; popovers small, single, transient.

### Cited Findings
- Primary button: the most likely action, responds to Return; never assign primary role to a destructive action; use prominent style for 1-2 buttons per view; distinguish by style, not size. — [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
- Push button label: start with verb, title-style capitalization; trailing ellipsis if it opens another window/view/app. — [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
- Square buttons and image buttons belong inside a view, not toolbars/window frame; help button: system-provided, one per window max, lower corner (opposite dismissal buttons in dialogs; lower-left/right in settings). — [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons)
- Segmented control: two or more segments; wide interfaces no more than about five to seven; equal width; nouns/noun phrases; text or images, not both; on macOS add introductory text, tooltips per segment. — [Segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls)
- Pop-up button: flat list of mutually exclusive options; use pull-down for actions, multi-select or submenus; provide useful default. — [Pop-up buttons](https://developer.apple.com/design/human-interface-guidelines/pop-up-buttons)
- Toggles on macOS: switches/checkboxes/radios belong in window body, not toolbars/status bars; checkbox for single on/off; radio groups of two to five, otherwise pop-up; mixed state for checkbox only; indent subordinate checkboxes. — [Toggles](https://developer.apple.com/design/human-interface-guidelines/toggles)
- Text fields: placeholder disappears on typing so add a label; secure field for passwords; validate at sensible times; combo box for text plus list. — [Text fields](https://developer.apple.com/design/human-interface-guidelines/text-fields)
- Alerts: use sparingly; not for pure info; not for common undoable actions; not at startup; up to three buttons; title two lines or fewer, specific (not "Error"); button titles one or two words describing result; Cancel always titled "Cancel"; avoid Yes/No; OK only for informational; default button trailing/top; Cancel leading/bottom; destructive style only for destructive action the person did not deliberately choose; destructive alerts always include Cancel; do not make Cancel default; Esc or Command-Period cancels. — [Alerts](https://developer.apple.com/design/human-interface-guidelines/alerts)
- macOS alerts: app icon appears automatically; suppression checkbox for repeating alerts; accessory view; help button; caution symbol `exclamationmark.triangle` sparingly. — [Alerts](https://developer.apple.com/design/human-interface-guidelines/alerts)
- Sheets: one at a time; always modal on macOS; buttons Cancel/Done/Back (do not show all three; Done pairs with Cancel); people do not expect to resize; reasonable default size; use a panel instead for repeated input (find/replace); dismissal via buttons not swipe. — [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)
- Popovers: few related tasks; one at a time, no cascading; nothing on top except an alert; do not use for warnings; dismiss on outside click or selection; only as big as needed; macOS popovers may be detachable into a panel. — [Popovers](https://developer.apple.com/design/human-interface-guidelines/popovers)

### Inferences
- Command palette is a custom pattern; follow search-field rules (type-to-filter, recent items, categorized results) and Esc dismissal. No HIG "command palette" page found (UNVERIFIED).

### Gaps
- Numeric control heights per size and exact button widths: not on fetched pages.

## Menus and keyboard shortcuts

### Takeaway
Provide the standard menu bar order and standard shortcuts; every toolbar/palette command should live in the menu bar. Modifier order and usage rules are explicit.

### Cited Findings
- Menu bar order: App name, File, Edit, Format, View, app-specific, Window, Help (Apple menu and extras system-managed). Disable unavailable items rather than hide. Use title-style capitalization, short one-word titles. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- App menu: About AppName (first, then separator), Settings…, Services, Hide, Hide Others, Show All, Quit. Settings is app-level only; document settings in File. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- View menu: Show/Hide Tab Bar, Show/Hide Toolbar, Customize Toolbar, Show/Hide Sidebar, Enter/Exit Full Screen; provide a View menu even if partial. Window menu: Minimize, Zoom (not full screen), Bring All to Front; provide a Window menu even with one window. Help menu: AppName Help. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- Edit menu: Undo, Redo, Cut, Copy, Paste, Paste and Match Style, Delete ("Delete" not "Erase"/"Clear"), Select All, Find submenu. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)
- Standard shortcuts (verified on Keyboards page): Command-Comma settings; Command-W close window; Command-Q quit; Command-N new; Command-O open; Command-S save; Shift-Command-S duplicate/Save As; Command-P print; Command-Z undo; Shift-Command-Z redo; Command-X/C/V; Command-A select all; Shift-Command-A deselect all; Command-F find; Command-G / Shift-Command-G find next/previous; Command-E use selection for find; Command-H hide; Option-Command-H hide others; Command-M minimize; Command-Period cancel; Command-Question mark help; Command-Grave next window; Control-Command-F full screen; Option-Command-T show/hide toolbar; Option-Command-I inspector; Esc cancel; Shift-Tab reverse focus; Control-F2 menu bar; Control-F5 toolbar. — [Keyboards](https://developer.apple.com/design/human-interface-guidelines/keyboards)
- Custom shortcut rules: Command main modifier, Shift secondary, Option sparingly, avoid Control; list modifiers in order Control, Option, Shift, Command; do not repurpose standard shortcuts; only for the most frequent commands; no Shift with upper character of two-character keys. — [Keyboards](https://developer.apple.com/design/human-interface-guidelines/keyboards)
- Support Full Keyboard Access. — [Keyboards](https://developer.apple.com/design/human-interface-guidelines/keyboards); [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Menus: ellipsis when more input is needed; submenus single level, consider new menu if more than about five items; dim unavailable; icons applied uniformly in a group; toggle labels change (Show/Hide); checkmark for attributes in effect. — [Menus](https://developer.apple.com/design/human-interface-guidelines/menus)
- Context menus: small number of frequently used actions relevant to current view. — [Menus](https://developer.apple.com/design/human-interface-guidelines/menus)
- Dynamic (Option-revealed) items: one modifier only, never the only way to do a task. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)

### Inferences
- Command palette shortcut: HIG gives no convention; avoid Command-Space (Spotlight) and Control-based combos; Shift-Command-P or Command-K style shortcuts are app-defined (UNVERIFIED as HIG convention).

### Gaps
- Destructive menu item guidance: page has none.
- Menu item counts for context menus: not given.

## Accessibility

### Takeaway
Numbers: text minimums, 4.5:1 / 3:1 contrast, hit targets, padding. Reduced motion guidance is qualitative.

### Cited Findings
- Contrast and hit-target numbers as above. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Ideally let people enlarge text at least 200% (applies where supported; macOS lacks Dynamic Type). — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Reduced motion: tighten springs, replace x/y/z transitions with fades, avoid depth animation along z, avoid animating into/out of blurs. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- VoiceOver: describe your interface and content; custom symbols need alternative text labels. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility); [SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)
- Do not override system keyboard shortcuts; test with Full Keyboard Access. — [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- Always provide increased-contrast variants for custom colors. — [Color](https://developer.apple.com/design/human-interface-guidelines/color)

### Inferences
- Electron: honor `prefers-reduced-motion`, `prefers-contrast`, `prefers-reduced-transparency`.

### Gaps
- Focus ring specs: not on fetched pages (only `keyboardFocusIndicatorColor` name).

## Motion, progress, empty states, errors, writing

### Takeaway
No animation duration numbers exist; principles are brief, purposeful, cancelable. Writing: verbs on buttons, no "Oops", fix-oriented errors.

### Cited Findings
- Motion: add purposefully; optional; feedback animations brief and precise; avoid motion on frequent interactions; let people cancel; macOS has no additional considerations; no durations given. — [Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- Progress: prefer determinate when possible; do not switch circular to bar; keep moving; avoid vague "loading"; macOS: avoid labeling a spinner; prefer spinner for background ops/small space; include Cancel when safe, Pause when interrupting has side effects. — [Progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators)
- Empty states: welcome and teach, relevant, clear next step button/link, not crucial info. — [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
- Errors: prevent first, show near the problem, no blame, say how to fix, no "Oops!"/"Uh-oh"; avoid "we". — [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
- Buttons/links: verb; "Click here" is banned; multi-step: Get Started, Continue/Next, Done. Choose one capitalization style per element type. — [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
- Capitalization by element (from component pages): buttons, menu items, column headings, segmented labels, panel titles use title-style; alert complete-sentence titles and informative text use sentence-style; notification body sentence case. Note: Writing page says title case is formal, sentence case casual, and to pick one per element type (so a sentence-case app is permissible, but Apple's own component pages specify title-style for menus and buttons). — [Alerts](https://developer.apple.com/design/human-interface-guidelines/alerts); [Menus](https://developer.apple.com/design/human-interface-guidelines/menus); [Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons); [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
- Avoid possessive pronouns ("Favorites" not "Your Favorites"). — [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)

### Inferences
- A short animation duration (e.g., 150-250 ms) is a common practice but is NOT from the HIG (UNVERIFIED).

### Gaps
- No HIG page found for a specific "empty state" component; guidance is only in Writing.

## Settings, onboarding, notifications

### Takeaway
Settings: Command-Comma, toolbar-tab panes, title tracks pane, restore last pane. Onboarding optional and brief. Notifications: no macOS-specific rules.

### Cited Findings
- Settings opened via App menu > Settings… (Command-Comma); do not add a settings button to the main toolbar; toolbar-switched panes with noncustomizable toolbar always showing active pane; dim minimize/maximize; title matches visible pane (single pane: "App Name Settings"); reopen to last viewed pane. — [Settings](https://developer.apple.com/design/human-interface-guidelines/settings)
- Settings content: good defaults, minimize number, do not ask for detectable info, do not duplicate system settings, keep task-specific options in context. — [Settings](https://developer.apple.com/design/human-interface-guidelines/settings)
- Setting labels: practical; explain what happens when ON; link directly to a setting rather than describing where. — [Writing](https://developer.apple.com/design/human-interface-guidelines/writing)
- Onboarding: optional/fast; after launch; context tips over flows; do not teach the system; postpone nonessential setup; request permission at the moment of need unless required to function; no licensing in onboarding. No macOS-specific considerations. — [Onboarding](https://developer.apple.com/design/human-interface-guidelines/onboarding)
- Notifications: concise; no duplicate notifications; use alert not notification for errors; up to four actions; no sensitive info; title-style titles, sentence-case body; badges only for unread counts; no macOS-specific considerations. — [Notifications](https://developer.apple.com/design/human-interface-guidelines/notifications)
- Menu bar extras: use symbol/icon (24 pt menu bar height), show a menu not a popover, let users decide to show it. — [The menu bar](https://developer.apple.com/design/human-interface-guidelines/the-menu-bar)

### Inferences
- A developer tool's provider/API-key setup is "required to function" so asking during first run is consistent with the onboarding permission rule.

### Gaps
- Pane window width/height numbers: not given.

## What changed with Liquid Glass (macOS 26) vs earlier, and what still holds

### Takeaway
New in the current HIG: Liquid Glass functional layer, floating sidebars, background extension effect, scroll edge effects, concentric bar-corner components, toolbar guidance updated Dec 16, 2025, and sidebar icon color guidance updated June 8, 2026. Most structural rules (menu order, shortcuts, alert wording, 13 pt body, accent-color behavior) are unchanged in kind.

### Cited Findings
- Changed/new: Liquid Glass layer for controls/navigation, not content; sidebars float and need content extended beneath; scroll edge effect replaces opaque backgrounds under controls; avoid custom toolbar backgrounds/tints; Liquid Glass color only for emphasis. — [Materials](https://developer.apple.com/design/human-interface-guidelines/materials); [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars); [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars); [Color](https://developer.apple.com/design/human-interface-guidelines/color)
- Change-log dates seen: Sidebars June 8, 2026 and June 9, 2025; Toolbars December 16, 2025. — [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars); [Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars)
- Still holds: 13 pt body/10 pt min, 28/20 pt control targets, accent color behavior, semantic colors, standard menus and shortcuts, alert rules. — pages cited above.

### Inferences
- Electron cannot render true Liquid Glass; emulate via `vibrancy` materials and avoid fake glass on content-layer elements.

### Gaps
- "Adopting Liquid Glass" technical overview page was not fetched; WWDC25 session 219 is only referenced, not read.
- Rules not fully verified from the second half of the Typography page and the Color page beyond the offset read; use live pages before citing precise values.
