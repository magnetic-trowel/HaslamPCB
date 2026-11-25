# LLM-driven circuit design

Scope: our attempts to go from a plain-language brief to a correct (not only well-formed) schematic. Not here: others' work -> [synthesis/schematic-generation-landscape](../../topics/synthesis/schematic-generation-landscape.md), [synthesis/part-selection-and-verification](../../topics/synthesis/part-selection-and-verification.md).
Keys: haslamsynth, typed circuit IR, LLM circuit design, schematic generation, independent LLM review

| Path | Status | One-line result | Page | Code |
|---|---|---|---|---|
| Typed circuit IR -> checked KiCad schematic, `.kicad_dru` and placement intent (haslamsynth) | worked (as a tool) | 4 designs build with 0 unwaived errors, clean ERC, exact netlist round trip | [haslamsynth.md](haslamsynth.md) | `tools/research/llm-design/synth/` |
| Four LLM-made designs with independent LLM review | partial | every review "not ready": 0–2 blockers, 4–7 majors per design, mostly invisible to the checks | [haslamsynth.md](haslamsynth.md#results) | `tools/research/llm-design/designs/` |
| Survey: schematic generation and part selection (others' work) | survey | code/typed IR beats raw `.kicad_sch` generation; ERC is a low bar | [schematic-generation-landscape](../../topics/synthesis/schematic-generation-landscape.md), [part-selection-and-verification](../../topics/synthesis/part-selection-and-verification.md) | — |

Related: [placement](../placement/README.md) (intent files are meant to feed a placer; not done yet), [research index](../README.md).
