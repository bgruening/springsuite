from os import system, mkdir
from os.path import basename, isfile, isdir

from spring_package.Alignment import Alignment
from spring_package.DBKit import DBKit
from spring_package.Energy import Energy
from spring_package.Molecule import Molecule
from spring_package.Utilities import getChain, getCrossReference, getName, getTemplates


def createPDB(identifier, pdbDatabase, outputName):
    pdb = getName(identifier)
    pdbDatabaseId = "%s.pdb" % pdb
    pdbDatabase.createFile(pdbDatabaseId, outputName)


def createMonomer(resultFile, identifier, pdbDatabase, outputName):
    print("Building model with: %s." % identifier)
    createPDB(identifier, pdbDatabase, outputName)
    template = Molecule(outputName)
    pdbChain = getChain(identifier)
    if pdbChain not in template.calpha:
        raise Exception("Chain not found in template [%s]" % pdbChain)
    chain = template.calpha[pdbChain]
    alignment = Alignment(resultFile)
    alignment.createModel(chain)
    template.saveChain(pdbChain, outputName)
    system("./build/pulchra %s" % outputName)


def TMalign(fileA, fileB, tmName="temp/tmalign"):
    system("build/TMalign %s %s -m %s.mat > %s.out" % (fileA, fileB, tmName, tmName))
    rotmat = list()
    with open("%s.mat" % tmName) as file:
        line = next(file)
        line = next(file)
        for i in range(3):
            line = next(file)
            rotmatLine = line[1:].split()
            rotmatLine = list(map(lambda x: float(x), rotmatLine))
            rotmatLine = [rotmatLine[1], rotmatLine[2], rotmatLine[3], rotmatLine[0]]
            rotmat.append(rotmatLine)
    with open("%s.out" % tmName) as file:
        for i in range(14):
            line = next(file)
        try:
            tmscore = float(line[9:17])
            line = next(file)
            tmscore = max(tmscore, float(line[9:17]))
        except Exception:
            raise Exception("TMalign::Failed to retrieve TMscore.")
    molecule = Molecule(fileA)
    for atom in molecule.atoms:
        molecule.applyMatrix(atom, rotmat)
    return tmscore, molecule


def TMalignAlignment(bioMolecule, templateChain, tmName="temp/tmalign"):
    aligned = list()
    with open("%s.out" % tmName) as file:
        for i in range(19):
            line = next(file)
        try:
            modelAlign = line
            line = next(file)
            alignment = line
            line = next(file)
            templateAlign = line
        except Exception:
            raise Exception("TMalign::Failed to retrieve TMalign results.")
    templateResidues = sorted(bioMolecule.calpha[templateChain].values(), key=lambda item: item["residueNumber"])
    templateIndex = 0
    for i in range(len(alignment)):
        t = templateAlign[i]
        if alignment[i] == ":":
            templateResidue = templateResidues[templateIndex]
            templateResidue["alignedResidue"] = modelAlign[i]
            aligned.append(templateResidue)
        if t != "-":
            templateIndex = templateIndex + 1
    return aligned


def getFrameworks(aTemplates, bTemplates, crossReference, minScore, maxTries):
    templateHits = list()
    for aTemplate in aTemplates:
        if aTemplate in crossReference:
            partners = crossReference[aTemplate]["partners"]
            templates = crossReference[aTemplate]["templates"]
            for pIndex in range(len(partners)):
                pTemplate = partners[pIndex]
                templatePair = templates[pIndex]
                if pTemplate in bTemplates:
                    minZ = min(aTemplates[aTemplate], bTemplates[pTemplate])
                    templateHits.append(dict(templatePair=templatePair, score=minZ))
    templateList = sorted(templateHits, key=lambda item: item["score"], reverse=True)
    print("Found %d templates." % len(templateList))
    for templateHit in templateList:
        if templateHit["score"] < minScore or maxTries == 0:
            break
        maxTries = maxTries - 1
        yield templateHit["templatePair"]


def createModel(args):
    print("SPRING - Complex Model Creation")
    aName = basename(args.a_hhr)
    bName = basename(args.b_hhr)
    print("Sequence A: %s" % aName)
    print("Sequence B: %s" % bName)
    aTop, aTemplates = getTemplates(args.a_hhr)
    bTop, bTemplates = getTemplates(args.b_hhr)
    if not isdir("temp"):
        mkdir("temp")
    outputName = args.output
    pdbDatabase = DBKit(args.index, args.database)
    crossReference = getCrossReference(args.cross)
    interfaceEnergy = Energy()
    createMonomer(args.a_hhr, aTop, pdbDatabase, "temp/monomerA.pdb")
    createMonomer(args.b_hhr, bTop, pdbDatabase, "temp/monomerB.pdb")
    maxScore = -9999
    maxInfo = None
    minScore = float(args.minscore)
    maxTries = int(args.maxtries)
    for [aTemplate, bTemplate] in getFrameworks(aTemplates, bTemplates, crossReference, minScore=minScore, maxTries=maxTries):
        print("Evaluating Complex Template: %s." % aTemplate)
        templateFile = "temp/template.pdb"
        createPDB(aTemplate, pdbDatabase, templateFile)
        templateMolecule = Molecule(templateFile)
        aTemplateChain = getChain(aTemplate)
        bTemplateChain = getChain(bTemplate)
        if aTemplateChain == bTemplateChain:
            bTemplateChain = "%s_0" % bTemplateChain
        print("Evaluating chain %s and %s..." % (aTemplate, bTemplate))
        biomolFound = False
        for biomolNumber in range(len(templateMolecule.biomol.keys())):
            if biomolNumber == 0:
                bioMolecule = templateMolecule
            else:
                bioMolecule = templateMolecule.createUnit(biomolNumber)
            if (len(bioMolecule.calpha.keys()) > 1
               and aTemplateChain in bioMolecule.calpha
               and bTemplateChain in bioMolecule.calpha):
                print("Evaluating biomolecule %i..." % biomolNumber)
                bioMolecule.saveChain(aTemplateChain, "temp/template_0.pdb")
                bioMolecule.saveChain(bTemplateChain, "temp/template_1.pdb")
                try:
                    coreTMscore, coreMolecule = TMalign("temp/monomerA.rebuilt.pdb", "temp/template_0.pdb")
                    coreAligned = TMalignAlignment(bioMolecule, aTemplateChain)
                    partnerTMscore, partnerMolecule = TMalign("temp/monomerB.rebuilt.pdb", "temp/template_1.pdb")
                    partnerAligned = TMalignAlignment(bioMolecule, bTemplateChain)
                except Exception as e:
                    print("Warning: Failed TMalign [%s]." % bTemplateChain)
                    print(str(e))
                    continue
                biomolFound = True
                TMscore = min(coreTMscore, partnerTMscore)
                print("  minTMscore : %5.2f" % TMscore)
                energy = -interfaceEnergy.get(coreAligned, partnerAligned)
                print("  Interaction: %5.2f" % energy)
                clashes = interfaceEnergy.getClashes(coreMolecule, partnerMolecule)
                print("  ClashRatio : %5.2f" % clashes)
                springScore = TMscore + energy * args.wenergy
                print("  SpringScore: %5.2f" % springScore)
                if springScore > maxScore:
                    maxScore = springScore
                    maxInfo = "%s\t %s\t %5.2f\t %5.2f\t %5.2f\t %5.2f\n" % (aName, bName, springScore, TMscore, energy, clashes)
                    coreMolecule.save(outputName, chainName="0")
                    partnerMolecule.save(outputName, chainName="1", append=True)
                    if args.showtemplate == "true":
                        bioMolecule.save(outputName, append=True)
            if biomolFound:
                break
    if maxInfo is not None:
        print("Completed.")
        print("SpringScore: %5.2f" % maxScore)
        print("Result stored to %s" % outputName)
        logExists = isfile(args.log)
        logFile = open(args.log, "a+")
        if not logExists:
            logFile.write("# Columns: NameA, NameB, Score, TMscore, Energy, Clashes\n")
        logFile.write(maxInfo)
        logFile.close()
    else:
        print("Warning: Failed to determine model.")
