#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/11 19:26
@Author  : alexanderwu
@File    : design_api.py
@Modified By: mashenquan, 2023/11/27.
            1. According to Section 2.2.3.1 of RFC 135, replace file data in the message with the file name.
            2. According to the design in Section 2.2.3.5.3 of RFC 135, add incremental iteration functionality.
"""
import json
from pathlib import Path
from typing import List

from metagpt.actions import Action, ActionOutput
from metagpt.config import CONFIG
from metagpt.const import (
    DATA_API_DESIGN_FILE_REPO,
    PRDS_FILE_REPO,
    SEQ_FLOW_FILE_REPO,
    SYSTEM_DESIGN_FILE_REPO,
    SYSTEM_DESIGN_PDF_FILE_REPO,
)
from metagpt.logs import logger
from metagpt.schema import Document, Documents
from metagpt.utils.common import CodeParser
from metagpt.utils.get_template import get_template
from metagpt.utils.mermaid import mermaid_to_file

templates = {
    "json": {
        "PROMPT_TEMPLATE": """
# Context
{context}

## Format example
{format_example}
-----
Role: You are an architect; the goal is to design a SOTA PEP8-compliant python system; make the best use of good open source tools
Requirement: Fill in the following missing information based on the context, each section name is a key in json
Max Output: 8192 chars or 2048 tokens. Try to use them up.

## Implementation approach: Provide as Plain text. Analyze the difficult points of the requirements, select the appropriate open-source framework.

## Python package name: Provide as Python str with python triple quoto, concise and clear, characters only use a combination of all lowercase and underscores

## File list: Provided as Python list[str], the list of ONLY REQUIRED files needed to write the program(LESS IS MORE!). Only need relative paths, comply with PEP8 standards. ALWAYS write a main.py or app.py here

## Data structures and interface definitions: Use mermaid classDiagram code syntax, including classes (INCLUDING __init__ method) and functions (with type annotations), CLEARLY MARK the RELATIONSHIPS between classes, and comply with PEP8 standards. The data structures SHOULD BE VERY DETAILED and the API should be comprehensive with a complete design. 

## Program call flow: Use sequenceDiagram code syntax, COMPLETE and VERY DETAILED, using CLASSES AND API DEFINED ABOVE accurately, covering the CRUD AND INIT of each object, SYNTAX MUST BE CORRECT.

## Anything UNCLEAR: Provide as Plain text. Make clear here.

output a properly formatted JSON, wrapped inside [CONTENT][/CONTENT] like format example,
and only output the json inside this tag, nothing else
""",
        "FORMAT_EXAMPLE": """
[CONTENT]
{
    "Implementation approach": "We will ...",
    "Python package name": "snake_game",
    "File list": ["main.py"],
    "Data structures and interface definitions": '
    classDiagram
        class Game{
            +int score
        }
        ...
        Game "1" -- "1" Food: has
    ',
    "Program call flow": '
    sequenceDiagram
        participant M as Main
        ...
        G->>M: end game
    ',
    "Anything UNCLEAR": "The requirement is clear to me."
}
[/CONTENT]
""",
    },
    "markdown": {
        "PROMPT_TEMPLATE": """
# Context
{context}

## Format example
{format_example}
-----
Role: You are an architect; the goal is to design a SOTA PEP8-compliant python system; make the best use of good open source tools
Requirement: Fill in the following missing information based on the context, note that all sections are response with code form separately
Max Output: 8192 chars or 2048 tokens. Try to use them up.
Attention: Use '##' to split sections, not '#', and '## <SECTION_NAME>' SHOULD WRITE BEFORE the code and triple quote.

## Implementation approach: Provide as Plain text. Analyze the difficult points of the requirements, select the appropriate open-source framework.

## Python package name: Provide as Python str with python triple quoto, concise and clear, characters only use a combination of all lowercase and underscores

## File list: Provided as Python list[str], the list of ONLY REQUIRED files needed to write the program(LESS IS MORE!). Only need relative paths, comply with PEP8 standards. ALWAYS write a main.py or app.py here

## Data structures and interface definitions: Use mermaid classDiagram code syntax, including classes (INCLUDING __init__ method) and functions (with type annotations), CLEARLY MARK the RELATIONSHIPS between classes, and comply with PEP8 standards. The data structures SHOULD BE VERY DETAILED and the API should be comprehensive with a complete design. 

## Program call flow: Use sequenceDiagram code syntax, COMPLETE and VERY DETAILED, using CLASSES AND API DEFINED ABOVE accurately, covering the CRUD AND INIT of each object, SYNTAX MUST BE CORRECT.

## Anything UNCLEAR: Provide as Plain text. Make clear here.

""",
        "FORMAT_EXAMPLE": """
---
## Implementation approach
We will ...

## Python package name
```python
"snake_game"
```

## File list
```python
[
    "main.py",
]
```

## Data structures and interface definitions
```mermaid
classDiagram
    class Game{
        +int score
    }
    ...
    Game "1" -- "1" Food: has
```

## Program call flow
```mermaid
sequenceDiagram
    participant M as Main
    ...
    G->>M: end game
```

## Anything UNCLEAR
The requirement is clear to me.
---
""",
    },
}

OUTPUT_MAPPING = {
    "Implementation approach": (str, ...),
    "Python package name": (str, ...),
    "File list": (List[str], ...),
    "Data structures and interface definitions": (str, ...),
    "Program call flow": (str, ...),
    "Anything UNCLEAR": (str, ...),
}

MERGE_PROMPT = """
## Old Design
{old_design}

## Context
{context}

-----
Role: You are an architect; The goal is to incrementally update the "Old Design" based on the information provided by the "Context," aiming to design a state-of-the-art (SOTA) Python system compliant with PEP8. Additionally, the objective is to optimize the use of high-quality open-source tools.
Requirement: Fill in the following missing information based on the context, each section name is a key in json
Max Output: 8192 chars or 2048 tokens. Try to use them up.

## Implementation approach: Provide as Plain text. Analyze the difficult points of the requirements, select the appropriate open-source framework.

## Python package name: Provide as Python str with python triple quoto, concise and clear, characters only use a combination of all lowercase and underscores

## File list: Provided as Python list[str], the list of ONLY REQUIRED files needed to write the program(LESS IS MORE!). Only need relative paths, comply with PEP8 standards. ALWAYS write a main.py or app.py here

## Data structures and interface definitions: Use mermaid classDiagram code syntax, including classes (INCLUDING __init__ method) and functions (with type annotations), CLEARLY MARK the RELATIONSHIPS between classes, and comply with PEP8 standards. The data structures SHOULD BE VERY DETAILED and the API should be comprehensive with a complete design. 

## Program call flow: Use sequenceDiagram code syntax, COMPLETE and VERY DETAILED, using CLASSES AND API DEFINED ABOVE accurately, covering the CRUD AND INIT of each object, SYNTAX MUST BE CORRECT.

## Anything UNCLEAR: Provide as Plain text. Make clear here.

output a properly formatted JSON, wrapped inside [CONTENT][/CONTENT] like "Old Design" format,
and only output the json inside this tag, nothing else
"""


class WriteDesign(Action):
    def __init__(self, name, context=None, llm=None):
        super().__init__(name, context, llm)
        self.desc = (
            "Based on the PRD, think about the system design, and design the corresponding APIs, "
            "data structures, library tables, processes, and paths. Please provide your design, feedback "
            "clearly and in detail."
        )

    async def run(self, with_messages, format=CONFIG.prompt_format):
        # Use `git diff` to identify which PRD documents have been modified in the `docs/prds` directory.
        prds_file_repo = CONFIG.git_repo.new_file_repository(PRDS_FILE_REPO)
        changed_prds = prds_file_repo.changed_files
        # Use `git diff` to identify which design documents in the `docs/system_designs` directory have undergone
        # changes.
        system_design_file_repo = CONFIG.git_repo.new_file_repository(SYSTEM_DESIGN_FILE_REPO)
        changed_system_designs = system_design_file_repo.changed_files

        # For those PRDs and design documents that have undergone changes, regenerate the design content.
        changed_files = Documents()
        for filename in changed_prds.keys():
            doc = await self._update_system_design(
                filename=filename, prds_file_repo=prds_file_repo, system_design_file_repo=system_design_file_repo
            )
            changed_files.docs[filename] = doc

        for filename in changed_system_designs.keys():
            if filename in changed_files.docs:
                continue
            doc = await self._update_system_design(
                filename=filename, prds_file_repo=prds_file_repo, system_design_file_repo=system_design_file_repo
            )
            changed_files.docs[filename] = doc
        if not changed_files.docs:
            logger.info("Nothing has changed.")
        # Wait until all files under `docs/system_designs/` are processed before sending the publish message,
        # leaving room for global optimization in subsequent steps.
        return ActionOutput(content=changed_files.json(), instruct_content=changed_files)

    async def _new_system_design(self, context, format=CONFIG.prompt_format):
        prompt_template, format_example = get_template(templates, format)
        prompt = prompt_template.format(context=context, format_example=format_example)
        # system_design = await self._aask(prompt)
        system_design = await self._aask_v1(prompt, "system_design", OUTPUT_MAPPING, format=format)
        # fix Python package name, we can't system_design.instruct_content.python_package_name = "xxx" since "Python
        # package name" contain space, have to use setattr
        setattr(
            system_design.instruct_content,
            "Python package name",
            system_design.instruct_content.dict()["Python package name"].strip().strip("'").strip('"'),
        )
        await self._rename_workspace(system_design)
        return system_design

    async def _merge(self, prd_doc, system_design_doc, format=CONFIG.prompt_format):
        prompt = MERGE_PROMPT.format(old_design=system_design_doc.content, context=prd_doc.content)
        system_design = await self._aask_v1(prompt, "system_design", OUTPUT_MAPPING, format=format)
        # fix Python package name, we can't system_design.instruct_content.python_package_name = "xxx" since "Python
        # package name" contain space, have to use setattr
        setattr(
            system_design.instruct_content,
            "Python package name",
            system_design.instruct_content.dict()["Python package name"].strip().strip("'").strip('"'),
        )
        system_design_doc.content = system_design.instruct_content.json()
        return system_design_doc

    @staticmethod
    async def _rename_workspace(system_design):
        if CONFIG.WORKDIR:  # Updating on the old version has already been specified if it's valid.
            return

        if isinstance(system_design, ActionOutput):
            ws_name = system_design.instruct_content.dict()["Python package name"]
        else:
            ws_name = CodeParser.parse_str(block="Python package name", text=system_design)
        CONFIG.git_repo.rename_root(ws_name)

    async def _update_system_design(self, filename, prds_file_repo, system_design_file_repo) -> Document:
        prd = await prds_file_repo.get(filename)
        old_system_design_doc = await system_design_file_repo.get(filename)
        if not old_system_design_doc:
            system_design = await self._new_system_design(context=prd.content)
            doc = Document(
                root_path=SYSTEM_DESIGN_FILE_REPO, filename=filename, content=system_design.instruct_content.json()
            )
        else:
            doc = await self._merge(prd_doc=prd, system_design_doc=old_system_design_doc)
        await system_design_file_repo.save(
            filename=filename, content=doc.content, dependencies={prd.root_relative_path}
        )
        await self._save_data_api_design(doc)
        await self._save_seq_flow(doc)
        await self._save_pdf(doc)
        return doc

    @staticmethod
    async def _save_data_api_design(design_doc):
        m = json.loads(design_doc.content)
        data_api_design = m.get("Data structures and interface definitions")
        if not data_api_design:
            return
        pathname = CONFIG.git_repo.workdir / Path(DATA_API_DESIGN_FILE_REPO) / Path(design_doc.filename).with_suffix("")
        await WriteDesign._save_mermaid_file(data_api_design, pathname)
        logger.info(f"Save class view to {str(pathname)}")

    @staticmethod
    async def _save_seq_flow(design_doc):
        m = json.loads(design_doc.content)
        seq_flow = m.get("Program call flow")
        if not seq_flow:
            return
        pathname = CONFIG.git_repo.workdir / Path(SEQ_FLOW_FILE_REPO) / Path(design_doc.filename).with_suffix("")
        await WriteDesign._save_mermaid_file(seq_flow, pathname)
        logger.info(f"Saving sequence flow to {str(pathname)}")

    @staticmethod
    async def _save_pdf(design_doc):
        file_repo = CONFIG.git_repo.new_file_repository(SYSTEM_DESIGN_PDF_FILE_REPO)
        await file_repo.save_pdf(doc=design_doc)

    @staticmethod
    async def _save_mermaid_file(data: str, pathname: Path):
        pathname.parent.mkdir(parents=True, exist_ok=True)
        await mermaid_to_file(data, pathname)
