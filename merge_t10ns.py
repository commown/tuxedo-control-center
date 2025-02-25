#!/usr/bin/env python3

"""Fonctions d'aide à la mise à jour des traductions de Tuxedo Control Center.

Le processus de mise à jour des traductions de TCC est le suivant :

+ Conventions : versions de Tuxedo x.y.z (ancienne) et X.Y.Z (nouvelle)

+ Fusionner X.Y.Z dans la branche de Commown et résoudre les conflits (souvent
  uniquement les numéros de version). Faire un git commit du résultat.

+ Regénérer le fichier xlf de la X.Y.Z avec `npm run gen-lang`

+ Exécuter ce script, qui pour chaque langue (fr, en, de) va :

  - Pour chaque trans-unit, créer 3 fichiers texte (format à déterminer)
    Hypothèse fait ici : la valeur de trans-unit est stable.

    * ancêtre : lang.<lang>.xlf.x.y.z
    * commown : lang.<lang>.xlf.x.y.z-commown[0-9]
    * nouvelle : lang.<lang>.xlf.X.Y.Z
      (note : lorsque lang=fr n'existe pas, ne rien faire donc)

  - Faire une fusion de ces fichiers avec ancêtre dans le fichier
    lang.<lang>.xlf.X.Y.Z-commown[0-9], en résolvant les éventuels conflits.

    Pour le Français copier simplement lang.fr.xlf.x.y.z-commown[0-9] dans
    lang.fr.xlf.X.Y.Z-commown[0-9]

    Cette opération permet de récupérer les modifications de traduction
    effectuées dans la nouvelle version ainsi que dans la version initiale de
    Commown.

  - Utiliser le fichier ainsi créé pour compléter les traductions manquantes
    dans une copie du fichier lang.xlf dans lang.<lang>.xlf

  - Compléter les traductions manquantes à la main.

"""

import subprocess

from lxml import etree
import three_merge


def merge(key, tu_id, commown, tuxedo, ancestor, lang):
    try:
        return three_merge.merge(
            commown[tu_id][key],
            tuxedo[tu_id][key],
            ancestor[tu_id][key],
            raise_on_conflict=True,
        )
    except three_merge.Conflict:
        print("Conflict on %s (lang %s). Commown version used." % (tu_id, lang))
        print("> Tuxedo version: %r." % tuxedo[tu_id][key])
        print("> Commown version: %r." % commown[tu_id][key])
        return commown[tu_id][key]


def _to_str(node):
    return etree.tostring(node).decode("utf-8")
    # _str = (node.text or "") + "".join(etree.tostring(e).decode("utf-8") for e in node)
    # return _str.strip()  # otherwise three_merge.merge may loop forever


def read_xlf_t10ns(fname):
    with open(fname, "rb") as fobj:
        doc = etree.fromstring(fobj.read())

    result = {}
    nsmap = {"a": doc.nsmap[None]}
    for tu in doc.xpath("//a:trans-unit", namespaces=nsmap):
        tu_id = tu.get("id")
        source = _to_str(tu.xpath("./a:source", namespaces=nsmap)[0])
        target = _to_str(tu.xpath("./a:target", namespaces=nsmap)[0])
        result[tu_id] = {"s": source, "t": target, "id": tu_id}

    return result


def cmd_out(*cmd):
    return subprocess.check_output(cmd).decode("utf-8").strip()


def git_extract(fpath, version, prefix):
    result_fpath = fpath + "." + prefix
    result = cmd_out("git", "show", ":".join([version, fpath]))
    with open(result_fpath, "w") as fobj:
        fobj.write(result)
    return result_fpath


def read_xlf_t10ns_at(xlf_fpath, version, prefix):
    try:
        fpath = git_extract(xlf_fpath, version, prefix)
    except subprocess.CalledProcessError:
        print("... returning empty translation list")
        return {}
    else:
        return read_xlf_t10ns(fpath)


def main(base_fpath, commown_vers, tuxedo_vers, raise_on_conflict=False):

    for lang in "en", "de", "fr":

        # Create a new base_doc for each lang to avoid editing the same object
        with open(base_fpath, "rb") as fobj:
            base_doc = etree.fromstring(fobj.read())

        nsmap = {"a": base_doc.nsmap[None]}
        file_node = base_doc.xpath("//a:file", namespaces=nsmap)[0]
        file_node.set("target-language", lang)

        # Get all xlf versions: ancestor, commown's and the new tuxedo one:
        xlf_fpath = base_fpath.replace("xlf", lang + ".xlf")

        ancestor_vers = cmd_out("git", "merge-base", commown_vers, tuxedo_vers)
        ancestor_xlf = read_xlf_t10ns_at(xlf_fpath, ancestor_vers, "ancestor")
        commown_xlf = read_xlf_t10ns_at(xlf_fpath, commown_vers, "commown")
        tuxedo_xlf = read_xlf_t10ns_at(xlf_fpath, tuxedo_vers, "tuxedo")

        # For each message in the new xlf, add a merged translation:
        common_tu_ids = set(ancestor_xlf) & set(commown_xlf) & set(tuxedo_xlf)
        for tu in base_doc.xpath("//a:trans-unit", namespaces=nsmap):
            tu_id = tu.get("id")
            source_node = tu.xpath("./a:source", namespaces=nsmap)[0]
            source = _to_str(source_node)
            target = None

            if tu_id in common_tu_ids:
                merged_source = merge(
                    "s", tu_id, commown_xlf, tuxedo_xlf, ancestor_xlf, lang,
                )
                if source == merged_source:
                    t10n = merge(
                        "t", tu_id, commown_xlf, tuxedo_xlf, ancestor_xlf, lang,
                    )
                    target = etree.fromstring(t10n)

            elif tu_id in commown_xlf:
                if source == commown_xlf[tu_id]["s"]:
                    target = etree.fromstring(commown_xlf[tu_id]["t"])

            elif tu_id in tuxedo_xlf:
                if source == tuxedo_xlf[tu_id]["s"]:
                    target = etree.fromstring(tuxedo_xlf[tu_id]["t"])

            if target is None:
                target = etree.Element("target", state="untranslated")
                target.text = source_node.text

            target.tail = source_node.tail
            tu.insert(tu.index(source_node) + 1, target)

        with open(xlf_fpath, "wb") as fobj:
            fobj.write(
                etree.tostring(base_doc, encoding="utf-8", xml_declaration=True)
            )


if __name__ == "__main__":
    import os.path as osp
    import sys

    base_fpath = osp.join("src", "ng-app", "assets", "locale", "lang.xlf")
    if not osp.isdir(".git") or not osp.isfile(base_fpath):
        print("Please run this script from the git root of TCC.")
        sys.exit(1)

    git_parents = cmd_out("git", "show", "-s", "--pretty=%P", "HEAD").split()
    if not len(git_parents) == 2:
        print(
            "Please run this script once you've merged the new Tuxedo version"
            " into commown master branch."
        )
        sys.exit(2)

    main(base_fpath, *git_parents)
