#!/usr/bin/python

import os
import sys
from os import path
from glob import glob
import multiprocessing as mp
import argparse
from PyFoam.Applications.PlotRunner import PlotRunner
from PyFoam.Applications.Runner import Runner
from PyFoam.Basics.TemplateFile     import TemplateFile
from subprocess import call
from PyFoam.RunDictionary.ParsedParameterFile   import ParsedParameterFile
from PyFoam.Applications.ClearCase import ClearCase
from PyFoam.Applications.Decomposer import Decomposer
import time, shutil
import sfoam

custom_reg_exp_contents = \
"""
// -*- C++ -*-
// File generated by PyFoam - sorry for the ugliness

FoamFile
{
 version 2.0;
 format ascii;
 class volVectorField;
 location "0";
 object U;
}

myFigure
{
  expr ".* Ux, Initial residual = (%f%).*";
  name Ux_myFigure;
  theTitle "Residuals for cases/trailer";
  titles
    (
      Ux
    );
  type regular;
}

AddToMyFigure1
{
  expr ".* Uy, Initial residual = (%f%).*";
  titles
    (
      Uy
    );
  type slave;
  master myFigure;
}

AddToMyFigure2
{
  expr ".* Uz, Initial residual = (%f%).*";
  titles
    (
      Uz
    );
  type slave;
  master myFigure;
}

AddToMyFigure3
{
  expr ".* p, Initial residual = (%f%).*";
  titles
    (
      p
    );
  type slave;
  master myFigure;
}

AddToMyFigure4
{
  expr ".* k, Initial residual = (%f%).*";
  titles
    (
      k
    );
  type slave;
  master myFigure;
}

"""

def runCasesFiles(names, cases, runArg, n):
    start = os.getcwd()
    for case in cases:
        os.chdir(case)
        # change customeRegexp
        customRegexpName = "customRegexp.base"
        with open(os.path.join(case, 'customRegexp.base'), 'w+') as fd:
            fd.write(custom_reg_exp_contents)
        title = "Residuals for %s" %case
        customRegexpFile = ParsedParameterFile(customRegexpName)
        customRegexpFile["myFigure"]["theTitle"] = ('"'+title+'"')
        customRegexpFile.writeFile()
        # delete the header lines - ParsedParameterFile requires them, but the customRegexp dosen't seem to work when their around...
        lines = open(customRegexpName).readlines()
        open('customRegexp', 'w').writelines(lines[12:])
        print n
        #  if n>1 make sure case is decomposed into n processors
        if n > 1:
            print "decomposing %(case)s" % locals()
            ClearCase(" --processors-remove %(case)s" % locals())
            Decomposer('--silent %(case)s %(n)s' % locals())

    #print "sfoam debug:", repr(sys.argv)
    os.chdir(start)

    p = mp.Pool(len(cases))
    def start_loop():
        print "runArg=%s" % runArg
        functions = {'plotRunner': run,
                     'Runner': runNoPlot,
                     'sfoam':runsfoam,}
        func = functions[runArg]
        pool_run_cases(p, names, cases, n, func)
    try:
        start_loop()
    except KeyboardInterrupt:
        try:
            p.close()
            p.join()
        except KeyboardInterrupt:
            p.terminate()

def runCases(args):
    case_dir = args.case_dir
    runArg = args.runArg
    n = args.n
    cases = [x for x in glob('%s*' % os.path.join(os.getcwd(), case_dir)) if os.path.isdir(x)]
    runCasesFiles(cases=cases, runArg=runArg, n=n)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-dir', help='directory of cases to use', default='.')
    parser.add_argument('--runArg', default="sfoam",help='choices are: plotRunner, Runner and sfoam')
    parser.add_argument('--n',default=1,help="number of processors for each parallel run. default is 1")
    args = parser.parse_args(sys.argv[1:])
    runCases(args)

def pool_run_cases(p, names, cases, n, f):
    if n > 1:
        procnr_args = '--procnr %s' % n
    else:
        procnr_args = ''
    args = list(enumerate([
        dict(name=name, target=case,
             args=("--progress %(procnr_args)s simpleFoam -case %(case)s" % locals()).split(),
             tasks=n
             )
               for name, case in zip(names, cases)]))
    for result in p.imap_unordered(f, args):
        print "%s: got %s" % (f.func_name, result)

def run((i, d)):
    target, args = d['target'], d['args']
    time.sleep(i * 2)
    print "got %s" % repr(args)
    return PlotRunner(args=args)

def runNoPlot((i, d)):
    target, args = d['target'], d['args']
    time.sleep(i * 2)
    print "got %s" % repr(args)
    return Runner(args=args)

def runsfoam((i, d)):
    tasks, target, args, name = d['tasks'], d['target'], d['args'], d['name']
    time.sleep(i * 2)
    print "---------------------- %s" % args
    print "sfoam - chdir to %s" % os.getcwd()
    print "calling sfoam tasks=%s target=%s" % (tasks, repr(target))
    return sfoam.sfoam(main="pyFoamRunner.py", tasks=tasks, target=target,
                       progname="/home/hanan/bin/OpenFOAM/sfoam.py",
                       solver='simpleFoam', name=name, verbose=False)

if __name__ == '__main__':
    main()
