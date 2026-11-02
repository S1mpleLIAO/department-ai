"""Run the approved fixed skill and remove blank trailing pages from generated forms."""
from pathlib import Path
import subprocess
from zipfile import ZipFile
from lxml import etree as ET

subprocess.run(["/usr/bin/python3", "/skill/scripts/generate_documents.py",
                "--profile", "/input/profile.json", "--job", "/input/job.json",
                "--output-dir", "/output"], check=True)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
for path in Path("/output").rglob("*.docx"):
    with ZipFile(path) as source:
        xml = ET.fromstring(source.read("word/document.xml"),
                            ET.XMLParser(resolve_entities=False, no_network=True))
        body = xml.find(W+"body")
        if body is None or len(body)<3: continue
        tail = body[-2]
        # Remove only an empty terminal paragraph after the complete table;
        # it otherwise creates a blank page when the table fills the page.
        if tail.tag!=W+"p" or body[-3].tag!=W+"tbl" or any((node.text or "").strip() for node in tail.iter(W+"t")) or tail.find(".//"+W+"drawing") is not None or tail.find(".//"+W+"sectPr") is not None:
            continue
        body.remove(tail)
        temporary=path.with_suffix(".docx.tmp")
        with ZipFile(temporary,"w") as dest:
            for item in source.infolist():
                dest.writestr(item,ET.tostring(xml,xml_declaration=True,encoding="UTF-8",standalone=True)
                              if item.filename=="word/document.xml" else source.read(item.filename))
    temporary.replace(path)
