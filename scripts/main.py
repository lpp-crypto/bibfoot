#!/usr/bin/env python3

# !FILE! Markdown notes need to refer to prior art and other
# ! references. To this end, we provide a script that replicates the
# ! usual latex workflow: first, we parse a markdown file to extract
# ! bibtex keys to generate a .aux file, then, we call bibtex on the
# ! result, and then we add/update a section at the end of the
# ! markdown file accordingly. For compatibily with github, the format
# ! to use in the markdown text is `[^key]`: it corresponds to a
# ! footnote. Note: any `:` in the key must be replaced by a `-`.



# Heavily based on code that is (for now still) a part of sboxU (see
# https://github.com/lpp-crypto/sboxU), the extraction wa done with
# the help of Claude.



# !SECTION! Preamble: imports and constants 
# ! ================================================================ 


import os
import re
from pathlib import Path
import argparse
import sys

from pylatexenc.latexwalker import LatexWalker, get_default_latex_context_db as _walker_ctx
from pylatexenc.latex2text import LatexNodes2Text, get_default_latex_context_db as _l2t_ctx
from pylatexenc.macrospec import std_macro



REFERENCE_TITLE = "References"
CITATION_RE = re.compile(r"\[\^[A-Za-z]+-[A-Za-z\+]+[0-9]*\]")



# !SECTION! Parsing the markdown and bbl files
# !=====================================================================
# ! Two classes are in charge of the relevant i/o operations: one for
# ! and one for the markdown file that needs to be updated, and one for
# ! the bbl file generated using bibtex.



# !SUBSECTION! The ReferenceCollectors class
# !--------------------------------------------------------------------
# ! Parses a markdown file line by while maintaining an internal
# ! state containing a list of all the references it has encountered.


class ReferencesCollector:
    """Scans a markdown file for [^key]-style citations, and creates a
    .aux file that can be parsed by bibtex.

    """

    def __init__(self, bib_path: str | list[str], verbose: bool = False):
        """Arguments:
        
        """
        self.verbose = verbose

        self.references = []
        self.seen = set()
        if isinstance(bib_path, str):
            self.bib_path = [ str(bib_path) ]
        else: # then it has to already be a list
            self.bib_path = [str(f) for f in bib_path]


    def maybe_add_reference(self, line: str) -> None:
        for hit in CITATION_RE.findall(line):
            # remove markdown-friendly artifacts
            ref = hit.replace("^", "").replace("-", ":")           
            if ref[0] == "[":
                ref = ref[1:]
            if ref[-1] == "]":
                ref = ref[:-1]
            # updating references list (if necessary)
            if ref not in self.seen:
                self.seen.add(ref)
                self.references.append(ref)
                if self.verbose:
                    print("found citation:", ref)

            
    def collect_citations(self, md_path : str) -> None:
        """Scan the markdown file for citation keys, stopping at the
        first line whose stripped text ends with "References".

        """
        with open(md_path, "r") as f:
            for line in f:
                if line.rstrip().endswith(REFERENCE_TITLE):
                    break
                self.maybe_add_reference(line)


        
    def generate_aux_from_markdown(self, md_path : str, aux_path : str, style : str="alpha") -> None:
        self.collect_citations(md_path)
        with open(aux_path, "w") as f:
            f.write(f"\\bibstyle{{{style}}}\n")
            # we need to remove the extensions from the files
            all_bib_files = ",".join([bib_file.replace(".bib", "")
                                      for bib_file in self.bib_path])
            f.write(f"\\bibdata{{{all_bib_files}}}\n")
            for key in self.references:
                f.write(f"\\citation{{{key}}}\n")

    

# !SUBSECTION! The .bbl parsing logic
# !---------------------------------------------------------------------
# ! Once a .aux has been extracted, we need to call `bibtex` on it 
# ! (you must do that manually, like in LaTeX), and then update the
# ! original mankdown file by rewriting its "References" section.



# !SUBSUBSECTION! Claude sorcery
# ! `pylatexenc` struggles with href; Claude came up with the
# ! following workaround. Somehow, it works!

_parse_context = _walker_ctx()
_parse_context.add_context_category(
    "href-fix",
    prepend=True,
    macros=[std_macro("href", False, 2)],  # exactly 2 mandatory args: {url}{text}
)
_converter = LatexNodes2Text(latex_context=_l2t_ctx())


def latex_to_markdown(latex_str: str) -> str:
    nodes = LatexWalker(latex_str, latex_context=_parse_context).get_latex_nodes()[0]
    return _converter.nodelist_to_text(nodes)


# !SUBSUBSECTION! Parsing the .bbl file and rewriting the .md file


def bbl_parse(aux_path : str):
    converter = LatexNodes2Text()
    
    result = []
    with open(aux_path, "r") as f:
        text = f.read()
        # thanks Claude for the regex
        for m in re.finditer(r"\\bibitem(?:\[.*?\])?\{(.+?)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})",
                             text, re.DOTALL):
            key, body = m.group(1), m.group(2).strip()
            # reformatting the key for markdown
            line = "[^" + key.replace(":", "-") + "]: "
            line += " ".join(latex_to_markdown(body).split())
            result.append(line)
        return result
    raise Exception("aux file not found")


def rewrite_references(md_path : str, bbl_path : str, verbose : bool = False) -> None:
    """Rewrite the markdown file in place: keep everything up to
    (not including) the first line ending in "References" -- or
    the whole file, if no such line exists -- then append a fresh
    "## References" section built from the corresponding bbl.

    """
    tmp_path = str(md_path) + ".tmp"
    content = bbl_parse(bbl_path)
    with open(md_path, "r") as original, open(tmp_path, "w") as updated:
        for line in original:
            if line.rstrip().endswith(REFERENCE_TITLE):
                break
            updated.write(line)
        updated.write("## {}\n\n".format(REFERENCE_TITLE))
        for line in content:
            updated.write(line + "\n\n")
            if verbose:
                print(line)
    os.replace(tmp_path, md_path)

    

# !SECTION! Logic for the script (main function)
# !=====================================================================



# !SUBSECTION! Functions performing the actual operations 

def cmd_aux(args: argparse.Namespace) -> int:
    md_file = args.markdown
    bib_files = args.bibtex
    style = args.style
    output = args.output if args.output else md_file.with_suffix(".aux")
 
    if not md_file.is_file():
        print(f"error: markdown file not found: {md_file}", file=sys.stderr)
        return 1
 
    missing = [b for b in bib_files if not b.is_file()]
    if missing:
        for b in missing:
            print(f"error: bibtex file not found: {b}", file=sys.stderr)
        return 1
 
    r = ReferencesCollector(bib_files)
    print(output)
    r.generate_aux_from_markdown(md_file, output, style=style)
    print(f"wrote {output}")
    return 0
 
 
def cmd_update(args: argparse.Namespace) -> int:
    md_file = args.markdown
 
    if not md_file.is_file():
        print(f"error: markdown file not found: {md_file}", file=sys.stderr)
        return 1
 
    bbl_file = args.bbl if args.bbl else md_file.with_suffix(".bbl")
    if not bbl_file.is_file():
        print(f"error: bbl file not found: {bbl_file}", file=sys.stderr)
        return 1
 
    rewrite_references(md_file, bbl_file)
    print(f"updated {md_file} using {bbl_file}")
    return 0



# !SUBSECTION! Building the parser
# !=====================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibfoot",
        description="adding a bibliography derived from bibtex files to the footer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # !SUBSECTION!aux subcommand
    
    aux_parser = subparsers.add_parser(
        "extract",
        help="Extract citation keys from a Markdown file and generate a .aux file.",
    )
    aux_parser.add_argument(
        "markdown",
        type=Path,
        help="Path to the Markdown file to scan for citation keys.",
    )
    aux_parser.add_argument(
        "bibtex",
        type=Path,
        nargs="+",
        help="One or more .bib files containing the bibliography data.",
    )
    aux_parser.add_argument(
        "-s", "--style",
        default="plain",
        help="Bibliography style to record in the .aux file (default: %(default)s).",
    )
    aux_parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output .aux file path (default: <markdown file>.aux).",
    )
    aux_parser.set_defaults(func=cmd_aux)

    # !SUBSUBSECTION! update subcommand 
    
    update_parser = subparsers.add_parser(
        "rewrite",
        help="Update a Markdown file's references section from a .bbl file.",
    )
    update_parser.add_argument(
        "markdown",
        type=Path,
        help="Path to the Markdown file to update.",
    )
    update_parser.add_argument(
        "-b", "--bbl",
        type=Path,
        default=None,
        help="Path to the .bbl file to use (default: <markdown file>.bbl).",
    )
    update_parser.set_defaults(func=cmd_update)
 
    return parser


# !SUBSECTION! Main logic
# !=====================================================================
 
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
 
 
if __name__ == "__main__":
    raise SystemExit(main())
