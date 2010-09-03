#!/usr/bin/env python
#
# testing of SPIDIR and other phylogeny algorithms
#

# python libs
import sys, os
import math, StringIO, copy, random

# rasmus libs
from rasmus import env
from rasmus import depend
from rasmus import stats
from rasmus import tablelib
from rasmus import treelib
from rasmus import util


from rasmus.bio import alignlib
from rasmus.bio import fasta
from rasmus.bio import phylo
from rasmus.bio import genomeutil






options = [
 ["o:", "outdir=", "outdir", "<output directory>",
    {"help": "directory to place output", 
     "single": True}],
 ["s:", "stree=", "stree", "<species tree>"],
 ["S:", "smap=", "smap", "<gene2species mapping>"],
 ["f:", "ext=", "ext", "<input file extension>"],
 ["t:", "treeext=", "treeext", "<correct tree extension>"],
 ["n:", "num=", "num", "<max number of trees to eval>",
    {"single": True,
     "default": 1000000}],
 ["N:", "nproc=", "nproc", "<max number of processors to use>",
    {"single": True,
     "default": 1000}],
 ["i:", "start=", "start", "<starting tree>", 
    {"single": True,
     "default": 0}],
 ["e:", "exec=", "exec", "<command to exec>"],     
 ["r", "results", "results", "", 
    {"help": "just compute results"}],
 ["R", "noresults", "noresults", "",
    {"single": True}],
 ["g:", "groups=", "groups", "<number of exec per group>",
    {"default": [4]}],
 ["P:", "statusdir=", "statusdir", "<status directory>",
    {"default": "sindir-test-status",
     "single": True}],
 ["L", "local", "local", "",
    {"help": "Do not distribute jobs"}],
 ["F", "force", "force", "",
    {"help": "Force rerun of all jobs"}],
 ["", "inputfiles=", "inputfiles", "{<files>}",
    {"single": True, 
     "parser": util.shellparser,
     "default": []}],
]


conf = util.parseOptions(sys.argv, options, quit=True, resthelp="<input files>")


# Pipeline setup
# decide whether to use default dispatch (LSF,BASH) or force BASH
if "local" in conf:
    pipeline = depend.Pipeline(conf["statusdir"], False, depend.BASH_DISPATCH)
else:
    pipeline = depend.Pipeline(conf["statusdir"])
pipeline.setLogOutput()


if depend.hasLsf():
    pipeline.setMaxNumProc(conf["nproc"])
else:
    # no need for parallelism
    pipeline.setMaxNumProc(1)


#
# filename conventions
#

def getBasenames(conf, infile):
    basename = infile.replace(conf["ext"][-1], "")
    return os.path.dirname(basename), os.path.basename(basename)

def getCorrectTree(conf, infile):
    basedir, basefile = getBasenames(conf, infile)
    return os.path.join(basedir, basefile + conf["treeext"][-1])

def getOutputTree(conf, infile):
    basedir, basefile = getBasenames(conf, infile)
    return os.path.join(conf["outdir"], basefile + ".tree")



def main(conf):
    env.addEnvPaths("DATAPATH")
    
    print "Pipeline is using dispatch: '%s'" % pipeline.dispatch
    
    if "results" in conf:
        makeReport(conf)
    else:
        testAll(conf)
        if not conf["noresults"]:
            makeReport(conf)


def testAll(conf):
    util.tic("testing")
    
    files = conf["REST"] + conf["inputfiles"]
        
    
    jobs = []
    start = int(conf["start"])
    num   = int(conf["num"])
    for infile in files[start:start+num]:
        jobs.append(runJob(conf, infile))
    jobs = filter(lambda x: x != None, jobs)
    
    groups = pipeline.addGroups("testgroup", jobs, int(conf["groups"][-1]))
    alljobs = pipeline.add("testall", "echo all", groups, 
                           dispatch=depend.BASH_DISPATCH)
    
    pipeline.reset()
    pipeline.run("testall")
    pipeline.process()
    
    util.toc()


def runJob(conf, infile):
    basedir, basefile = getBasenames(conf, infile)
    
    # skip tests when output tree already exists
    if "force" not in conf and \
       os.path.exists("%s/%s.tree" % (conf["outdir"], basefile)):
        util.log("skip '%s/%s.tree' output exists " % (conf["outdir"], basefile))
        return None
    
    cmd = conf["exec"][-1]
    cmd = cmd.replace("$FILE", basefile)
    cmd = cmd.replace("$DIR", basedir)
    
    jobname = pipeline.add("job_" + basefile, cmd, [])
    
    return jobname


def checkOutput(conf, infile, stree, gene2species):
    basedir, basefile = getBasenames(conf, infile)
    outfile = getOutputTree(conf, infile)
    correctTreefile = getCorrectTree(conf, infile)

    if not os.path.exists(outfile):
        return None, None 

    tree1 = treelib.readTree(outfile)
    tree2 = treelib.readTree(correctTreefile)

    phylo.reconRoot(tree1, stree, gene2species, newCopy=False)
    phylo.reconRoot(tree2, stree, gene2species, newCopy=False)
        
    return tree1, tree2


def makeReport(conf):
    util.tic("make report")

    gene2species = genomeutil.readGene2species(* map(env.findFile, 
                                                     conf["smap"]))
    stree = treelib.readTree(env.findFile(conf["stree"][-1]))
    
    infiles = conf["REST"] + conf["inputfiles"]
    
    results = []
    counts = util.Dict(1, 0)
    
    resultstab = tablelib.Table(
                    headers=["treeid", "correct",
                             "rferror", "tree", "correct_tree", 
                             "species_hash"])
    treehashes = []
    
    
    for infile in infiles:
        util.logger(infile)
        basedir, basefile = getBasenames(conf, infile)
        tree1, tree2 = checkOutput(conf, infile, stree, gene2species)
        
        
        if tree1 == None:
            continue
            
        
        error = phylo.robinsonFouldsError(tree1, tree2)
        
        hash1 = phylo.hashTree(tree1)
        hash2 = phylo.hashTree(tree2)
        
        # make a species hash
        shash1 = phylo.hashTree(tree1, gene2species)
        shash2 = phylo.hashTree(tree2, gene2species)
        counts[(shash1,shash2)] += 1
        
        results.append([basefile, hash1 == hash2, error])
        resultstab.add(treeid=basefile,
                       tree=tree1.getOnelineNewick(),
                       correct_tree=tree2.getOnelineNewick(),
                       correct= (hash1 == hash2),
                       rferror=error,
                       species_hash=shash1)
        
    
    
    # print final results    
    reportfile = os.path.join(conf["outdir"], "results")
    out = file(reportfile, "w")

    total = len(results)
    ncorrect = util.counteq(True, util.cget(results, 1))
    nwrong = util.counteq(False, util.cget(results, 1))
    
    rfs = util.cget(results, 2)
    if len(rfs) > 0:
        rferror = stats.mean(rfs)
    else:
        rferror = -1
    
    

    
    print >>out, "total:         %d" % total
    print >>out, "#correct:      %d (%f%%)" % (ncorrect, 100*ncorrect / float(total))
    print >>out, "#incorrect:    %d (%f%%)" % (nwrong, 100*nwrong / float(total))
    print >>out, "avg. RF error: %f" % rferror
    print >>out
    print >>out


    util.printcols(results, out=out)
    
    # print out shash counts
    mat = []
    items = counts.items()
    items.sort(key=lambda x: -x[1])
    tot = float(sum(counts.values()))
    for (tree1, tree2), num in items:
        if tree1 == tree2: c = "*"
        else: c = " "
        mat.append([c, tree1, num, num/tot])
        mat.append([c, tree2, "", ""])
        mat.append(["", "", "", ""])
    
    util.printcols(mat, out=out)

    
    resultstab.comments.extend([
        "#",
        "# total:         %d" % total,
        "# correct:      %d (%f%%)" % (ncorrect, 100*ncorrect / float(total)),
        "# incorrect:    %d (%f%%)" % (nwrong, 100*nwrong / float(total)),
        "# avg. RF error: %f" % rferror,
        "#"])
    
    resultstab.write(os.path.join(conf["outdir"], "results.tab"))
    histtrees = tablelib.histTable(resultstab.cget("species_hash"))
    histtrees.write(os.path.join(conf["outdir"], "histtrees.tab"))
        

    util.toc()



def testOrthologs(tree1, tree2, stree, gene2species):
    recon1 = phylo.reconcile(tree1, stree, gene2species)
    recon2 = phylo.reconcile(tree2, stree, gene2species)
    
    orths1 = phylo.findAllOrthologs(tree1, stree, recon1)
    orths2 = phylo.findAllOrthologs(tree2, stree, recon2)
    
    set1 = set(map(tuple, orths1))
    set2 = set(map(tuple, orths2))
    
    ngenes = len(tree2.leaves())
    nonorths = ngenes * (ngenes + 1) / 2 - len(set2)
    
    # sensitivity and specificity
    overlap = set1 & set2
    tp = len(overlap)
    fp = len(set1) - len(overlap)
    fn = len(set2) - len(overlap)
    tn = nonorths - fp
    
    return [tp, fn, fp, tn]




main(conf)