import sys
import os
import multiprocessing
import itertools
import glob
import shutil
import subprocess
import translateSTL
from datetime import datetime
from os import path, makedirs
from math import pi, sin, cos, floor, log, sqrt
import scipy.interpolate as sc
from numpy import linspace, meshgrid, genfromtxt, zeros
from matplotlib.backends.backend_pdf import PdfPages

from PyFoam.RunDictionary.SolutionDirectory     import SolutionDirectory
from PyFoam.RunDictionary.ParsedParameterFile   import ParsedParameterFile
from PyFoam.Applications.ClearCase              import ClearCase
from PyFoam.Applications.Runner                 import Runner
from PyFoam.Basics.TemplateFile                 import TemplateFile
from PyFoam.Applications.Decomposer             import Decomposer
from PyFoam.Execution.BasicRunner 		        import BasicRunner

sys.path.append('../')
from runCases import runCasesFiles as runCases
from windrose import WindroseAxes

from matplotlib import pyplot as plt
import matplotlib.cm as cm
from numpy.random import random
from numpy import arange

def hist_to_time(distribution, values, n=1000):
    """
    [10,8,6] [0.1,0.5,0.4]
    [1,1,1,1..1,2,2,..2,3,3,..3]
    10          8       6
    """
    if sum(distribution) != 1.0:
        print "warning: hist_to_time input distribution doesn't sum to one, fixing locally"
        D = sum(distribution)
        distribution = [x/D for x in distribution]
    plurality = [int(d * n) for d in distribution]
    out_val = []
    for val in values:
        out_val.append(sum([[v]*p for p, v in zip(plurality, val)], []))
    return out_val

def read_dict_string(d, key):
    """
    to allow using a filename like so:
    template "/home/hanan/bin/OpenFOAM/windpyfoam/test_template";

    if you remove the '"' you get an Illegal '/' used message
    """
    val = d[key]
    if len(val) > 0 and val[0] == '"':
        assert(val[-1] == '"')
        val = val[1:-1]
    return val

class Solver(object):
    def __init__(self, reporter, plots):
        self._r = reporter
        self._plots = plots
        self._fig_n = 1

    def initial_wind_rose_axes(self):
        fig = self.newFigure(figsize=(8, 8), dpi=80, facecolor='w', edgecolor='w')
        rect = [0.1, 0.1, 0.8, 0.8]
        ax = WindroseAxes(fig, rect, axisbg='w')
        fig.add_axes(ax)
        return ax

    def initial_wind_rose_legend(self, ax):
        plt = self._r.plot
        l = ax.legend(axespad=-0.10)
        plt.setp(l.get_texts(), fontsize=8)

    def create_block_mesh_dict(self, work, wind_dict, params):
        phi = params['phi']
        cell_size = params["cell_size"]
        SHM = wind_dict["SHMParams"]
        Href = SHM["domainSize"]["domZ"]
        domainSize = SHM["domainSize"]
        lup, ldown, d = domainSize["fXup"], domainSize["fXdown"], domainSize["fY"]
        x0, y0 = (SHM["centerOfDomain"]["x0"],
                SHM["centerOfDomain"]["y0"])
        sin_phi = sin(phi)
        cos_phi = cos(phi)
        x1 = x0 - (lup * sin_phi + d / 2 * cos_phi)
        y1 = y0 - (lup * cos_phi - d / 2 * sin_phi)
        x2 = x0 - (lup * sin_phi - d / 2 * cos_phi)
        y2 = y0 - (lup * cos_phi + d / 2 * sin_phi)
        x3 = x0 + (ldown * sin_phi + d / 2 * cos_phi)
        y3 = y0 + (ldown * cos_phi - d / 2 * sin_phi)
        x4 = x0 + (ldown * sin_phi - d / 2 * cos_phi)
        y4 = y0 + (ldown * cos_phi + d / 2 * sin_phi)
        n = floor(d / cell_size)
        m = floor((lup+ldown) / cell_size)
        q = floor((Href - domainSize["z_min"]) / cell_size)
        if n == 0 or m == 0 or q == 0:
            self._r.error("invalid input to block mesh dict:\n" +
                          ("d = %(d)f, l = %(l)f, Href = %(Href)f, cell = %(cell)f, cell_size = %(cell_size)f" % locals()) +
                          ("n = %(n)f, m = %(m)f, q = %(q)f" % locals()))
        assert(n > 0 and m > 0 and q > 0)
        bmName = path.join(work.constantDir(),"polyMesh/blockMeshDict")
        template = TemplateFile(bmName+".template")
        template.writeToFile(bmName,
            {'X0':x1,'X1':x2,'X2':x3,'X3':x4,
            'Y0':y1,'Y1':y2,'Y2':y3,'Y3':y4,
            'Z0':Href,'n':int(n),'m':int(m),'q':int(q),
            'z_min':domainSize["z_min"]})

    def create_SHM_dict(self, work, wind_dict, params):
        self._r.status("calculating SHM parameters")
        phi = params['phi']
        SHM = wind_dict["SHMParams"]
        domainSize = SHM['domainSize']
        a = domainSize['refinement_length']
        H = domainSize['typical_height']
        Href = SHM["domainSize"]["domZ"]
        cell_size = params['cell_size'] # blockMesh cell size
        z_cell = cell_size
        zz = SHM["pointInDomain"]["zz"]
        x0, y0 = (SHM["centerOfDomain"]["x0"],
                SHM["centerOfDomain"]["x0"])
        i = params['i']
        z0 = wind_dict["caseTypes"]["windRose"]["windDir"][i][2]
        # calculating refinement box positions
        l1, l2, h1, h2 = 2*a, 1.3*a, 4*H, 2*H # refinement rules - Martinez 2011
        sp = sin(phi)
        cp = cos(phi)
        #enlarging to take acount of the rotation angle
        def calc_box(l, h):
            tx1, ty1, tz1 = x0 - l*(sp+cp), y0 - l*(cp-sp), domainSize["z_min"]
            tx2, ty2, tz2 = x0 + l*(sp+cp), y0 + l*(cp-sp), h
            return (min(tx1, tx2), min(ty1, ty2), min(tz1, tz2),
                    max(tx1, tx2), max(ty1, ty2), max(tz1, tz2))
        (refBox1_minx, refBox1_miny, refBox1_minz,
        refBox1_maxx, refBox1_maxy, refBox1_maxz) = calc_box(l1, h1)
        (refBox2_minx, refBox2_miny, refBox2_minz,
        refBox2_maxx, refBox2_maxy, refBox2_maxz) = calc_box(l2, h2)
        assert(refBox1_minx < refBox1_maxx)
        assert(refBox1_miny < refBox1_maxy)
        assert(refBox1_minz < refBox1_maxz)
        assert(refBox2_minx < refBox2_maxx)
        assert(refBox2_miny < refBox2_maxy)
        assert(refBox2_minz < refBox2_maxz)

        # changing snappyHexMeshDict - with parsedParameterFile

        # case 1 - an stl file describing a rectangular domain larger then the blockMesh control volume
        if SHM["rectanguleDomainSTL"]:
            shutil.copyfile(path.join(work.systemDir(), "snappyHexMeshDict_rectanguleDomain"), \
                        path.join(work.systemDir(), "snappyHexMeshDict"))
        # case 2 - an stl file describing a single hill, with edges at z_min
        else:
            shutil.copyfile(path.join(work.systemDir(), "snappyHexMeshDict_singleHill"), \
                        path.join(work.systemDir(), "snappyHexMeshDict"))

        # changes that apply to both cases
        SHMDict = ParsedParameterFile(
            path.join(work.systemDir(), "snappyHexMeshDict"))
        # changing refinement boxes around center reigon
        SHMDict["geometry"]["refinementBox1"]["min"] = \
            "("+str(refBox1_minx)+" "+str(refBox1_miny)+" "+str(refBox1_minz)+")"
        SHMDict["geometry"]["refinementBox1"]["max"] = \
            "("+str(refBox1_maxx)+" "+str(refBox1_maxy)+" "+str(refBox1_maxz)+")"
        SHMDict["geometry"]["refinementBox2"]["min"] = \
            "("+str(refBox2_minx)+" "+str(refBox2_miny)+" "+str(refBox2_minz)+")"
        SHMDict["geometry"]["refinementBox2"]["max"] = \
            "("+str(refBox2_maxx)+" "+str(refBox2_maxy)+" "+str(refBox2_maxz)+")"
        # changing inlet refinement reigon - crude correction to SHM layer fault at domain edges
        lup, ldown, d = domainSize["fXup"], domainSize["fXdown"], domainSize["fY"]
        x1 = x0 - (lup * sp + d / 2 * cp)
        y1 = y0 + (lup * cp - d / 2 * sp)
        x3 = x0 - ((lup - cell_size) * sp + d / 2 * cp)
        y3 = y0 - ((lup - cell_size) * cp - d / 2 * sp)

        SHMDict["geometry"]["upwindbox1"]["min"] = \
            "("+str(min(x1,x3))+" "+str(min(y1,y3))+" "+str(domainSize["z_min"])+")"
        SHMDict["geometry"]["upwindbox1"]["max"] = \
            "("+str(max(x1,x3))+" "+str(max(y1,y3))+" "+str(domainSize["z_min"]+cell_size/3)+")"
        """x1 = x0 + (ldown * sp + d / 2 * cp)
        y1 = y0 + (ldown * cp - d / 2 * sp)
        x3 = x0 + ((ldown - cell_size) * sp - d / 2 * cp)
        y3 = y0 + ((ldown - cell_size) * cp + d / 2 * sp)

        SHMDict["geometry"]["refinementOutlet"]["min"] = \
            "("+str(min(x1,x3))+" "+str(min(y1,y3))+" "+str(domainSize["z_min"])+")"
        SHMDict["geometry"]["refinementOutlet"]["max"] = \
            "("+str(max(x1,x3))+" "+str(max(y1,y3))+" "+str(domainSize["z_min"]+cell_size)+")"
        """
        # changing location in mesh
        SHMDict["castellatedMeshControls"]["locationInMesh"] = "("+str(x0)+" "+str(y0)+" "+str(zz)+")"
        levelRef = SHM["cellSize"]["levelRef"]
        SHMDict["castellatedMeshControls"]["refinementSurfaces"]["terrain"]["level"] = \
            "("+str(levelRef)+" "+str(levelRef)+")"
        SHMDict["castellatedMeshControls"]["refinementRegions"]["upwindbox1"]["levels"] =  \
            "(("+str(1.0)+" "+str(min(levelRef * 2,4))+"))"

        SHMDict["castellatedMeshControls"]["refinementRegions"]["refinementBox1"]["levels"] =  \
            "(("+str(1.0)+" "+str(int(round(levelRef/2)))+"))"
        SHMDict["castellatedMeshControls"]["refinementRegions"]["refinementBox2"]["levels"] =  \
            "(("+str(1.0)+" "+str(levelRef)+"))"

        r = SHM["cellSize"]["r"]
        SHMDict["addLayersControls"]["expansionRatio"] = r
        fLayerRatio = SHM["cellSize"]["fLayerRatio"]
        SHMDict["addLayersControls"]["finalLayerThickness"] = fLayerRatio
        # calculating finalLayerRatio for getting
        zp_z0 = SHM["cellSize"]["zp_z0"]
        firstLayerSize = 2 * zp_z0 * z0
        L = min(log(fLayerRatio/firstLayerSize*z_cell/2**levelRef) / log(r) + 1,12)
        SHMDict["addLayersControls"]["layers"]["terrain_solid"]["nSurfaceLayers"] = int(round(L))

        # changes that apply only to case 2
        if not(SHM["rectanguleDomainSTL"]):
            SHMDict["geometry"]["groundSurface"]["pointAndNormalDict"]["basePoint"] = \
                "( 0 0 "+str(domainSize["z_min"])+")"
            SHMDict["castellatedMeshControls"]["refinementRegions"]["groundSurface"]["levels"] = \
                "(("+str(h2/2)+" "+str(levelRef)+") ("+str(h1/2)+" "+str(int(round(levelRef/2)))+"))"
            SHMDict["addLayersControls"]["layers"]["ground"]["nSurfaceLayers"] = int(round(L))
        SHMDict.writeFile()



    def create_boundary_conditions_dict(self, work, wind_dict, params):
        #--------------------------------------------------------------------------------------
        # changing inlet profile - - - - according to Martinez 2010
        #--------------------------------------------------------------------------------------
        phi = params['phi']
        i = params['i']
        SHM = wind_dict['SHMParams']
        kEpsParams = wind_dict['kEpsParams']
        k = kEpsParams['k'] # von karman constant
        z0 = wind_dict["caseTypes"]["windRose"]["windDir"][i][2] # TODO: calculated per wind direction using roughness2foam
        us = wind_dict["caseTypes"]["windRose"]["windDir"][i][4] 
        Href = SHM['domainSize']['domZ']
        TKE = us**2 * wind_dict["caseTypes"]["windRose"]["windDir"][i][3]
        Cmu = us / TKE**2
        # change inlet profile
        z_min = wind_dict['SHMParams']['domainSize']['z_min']
        Uref = Utop = us / k * log((Href - z_min) / z0)
        # 1: changing ABLConditions
        bmName = path.join(work.initialDir(),"include", "ABLConditions")
        template = TemplateFile(bmName + ".template")
        template.writeToFile(bmName,
            {'us':us,'Uref':Uref,'Href':Href,'z0':z0,
            'xDirection':sin(phi),'yDirection':cos(phi)})
        # 2: changing initialConditions
        bmName = path.join(work.initialDir(),"include", "initialConditions")
        template = TemplateFile(bmName + ".template")
        template.writeToFile(bmName,{'TKE':TKE})
        # 3: changing initial and boundary conditions for z0
        # changing z0 in nut, inside nutkAtmRoughWallFunction - for rectanguleDomainSTL = 0 for both terrain and ground patches
        nutFile = ParsedParameterFile(path.join(work.initialDir(), "nut"))
        if SHM["rectanguleDomainSTL"]:
            nutFile["boundaryField"]["ground"]["z0"].setUniform(z0)
            nutFile["boundaryField"]["terrain_.*"]["z0"].setUniform(z0)
        else:
            nutFile["boundaryField"]["ground"]["z0"].setUniform(SHM["ground_z0"])
            nutFile["boundaryField"]["terrain_.*"]["z0"].setUniform(SHM["terrain_z0"])
        nutFile.writeFile()
        # 3: changing transport properties
        transportFile = ParsedParameterFile(path.join(work.constantDir(),'transportProperties'))
        transportFile['nu'] = "nu [0 2 -1 0 0 0 0] " + str(wind_dict['simParams']['nu'])
        transportFile.writeFile()

    def create_case(self, wind_dict, params):
        """
        0. cloning case
        1. creating snappyHexMeshDict and blockMeshdict according to flow direction and other parameters
        2. creating the blockMesh
        3. change the boundary conditions
        4. decomposing the domain
        5. creating the snappyHexMesh - running in parallel (sfoam.py or not - depending on user input)
        6. decomposing the created mesh
        """
        #--------------------------------------------------------------------------------------
        # cloning case
        #--------------------------------------------------------------------------------------
        target = params['case_dir']
        target = os.path.realpath(target)
        if not os.path.exists(target):
            makedirs(target)
        template = read_dict_string(wind_dict, 'template')
        self._r.debug("template = %r, target = %r" % (template, target))
        orig = SolutionDirectory(template,
                                archive=None,
                                paraviewLink=False)
        work = orig.cloneCase(target)

        #--
        # creating dictionaries
        #--
        if wind_dict['procnr'] > multiprocessing.cpu_count():
            self._r.warn('wind_dict contains a higher processor number then the machine has')
            wind_dict['procnr'] = min(wind_dict['procnr'], multiprocessing.cpu_count())
        phi = params['wind_dir'] * pi / 180
        params['phi'] = phi # - pi/180 * 90
        self._r.status('creating block mesh dictionary')
        self.create_block_mesh_dict(work, wind_dict, params)
        self._r.status('creating snappy hex mesh dictionary')
        self.create_SHM_dict(work, wind_dict, params)
        self._r.status('creating boundary conditions dictionary')
        self.create_boundary_conditions_dict(work, wind_dict, params)
        self._r.status('running block mesh')
        self.run_block_mesh(work)
        self._r.status('running decompose')
        self.run_decompose(work, wind_dict)
        self._r.status('running snappy hex mesh')
        self.run_SHM(work, wind_dict)
        self._r.status('running second decompose')
        self.run_decompose(work, wind_dict)
        return work

    def run_decompose(self, work, wind_dict):
        if wind_dict['procnr'] < 2:
            self._r.status('skipped decompose')
            return
        ClearCase(args=work.name+'  --processors-remove')
        Decomposer(args=[work.name, wind_dict['procnr']])

    def run_block_mesh(self, work):
        blockRun = BasicRunner(argv=["blockMesh", '-case', work.name],
                            silent=True, server=False, logname="blockMesh")
        self._r.status("Running blockMesh")
        blockRun.start()
        if not blockRun.runOK():
            self._r.error("there was an error with blockMesh")

    def mpirun(self, procnr, argv, output_file):
        # TODO: use Popen and supply stdout for continous output monitor (web)
        assert(type(procnr) is int)
        args = ' '.join(argv)
        os.system('mpirun -np %(procnr)s %(args)s | tee %(output_file)s' % locals())

    def run_SHM(self, work, wind_dict):
        if wind_dict["procnr"] > 1:
            self._r.status("Running SHM parallel")
            decomposeDict = ParsedParameterFile(
            path.join(work.systemDir(), "decomposeParDict"))
            decomposeDict["method"] = "ptscotch"
            decomposeDict.writeFile()
            self.mpirun(procnr=wind_dict['procnrSnappy'], argv=['snappyHexMesh',
                '-overwrite', '-case', work.name],output_file=path.join(work.name, 'SHM.log'))
            print 'running clearCase'
            ClearCase(args=work.name+'  --processors-remove')
        else:
            SHMrun = BasicRunner(argv=["snappyHexMesh",
                                '-overwrite','-case',work.name],
                            server=False,logname="SHM")
            self._r.status("Running SHM uniprocessor")
            SHMrun.start()

    def makedirs(self, d):
        self._r.debug('creating %r' % d)
        os.makedirs(d)

    def grid_convergance_params_generator(self, wind_dict):
        """
        yields names of case directories
        """
        grid_convergence = wind_dict["caseTypes"]["gridConvergenceParams"]
        gridRange = grid_convergence['gridRange']
        template = read_dict_string(wind_dict, 'template')
        wind_dir = grid_convergence['windDir']
        for i, cell_size in enumerate(gridRange):
            case_dir = os.path.join(wind_dict['runs'],
                                '%(template)s_grid_%(cell_size)s' % locals())
            yield dict(case_dir=case_dir, wind_dir=wind_dir, cell_size=cell_size,
                    name='grid_convergence %d: cell_size=%d, wind_dir=%d' % (i, cell_size, wind_dir))

    def wind_rose_params_generator(self, wind_dict):
        """
        yields names of case directories
        one for each direction from wind rose
        """
        windRose = wind_dict['caseTypes']["windRose"]
        template = read_dict_string(wind_dict, 'template')
        cell_size = windRose['blockMeshCellSize']
        for i, (_weight, wind_dir, _z0, _TKE_us2, _us) in enumerate(windRose['windDir']):
            case_dir = os.path.join(wind_dict['runs'],
                                '%(template)s_rose_%(wind_dir)s' % locals())
            yield dict(case_dir = case_dir, i = i, wind_dir = wind_dir, cell_size = cell_size,
                    name='wind_rose %d: cell_size=%d, wind_dir=%d' % (i, cell_size, wind_dir))

    def run_directory(self, prefix):
        now = datetime.now()
        pristine = now.strftime(prefix + '_%Y%m%d_%H%M%S')
        if os.path.exists(pristine):
            if os.path.exists(pristine + '_1'):
                last = max([try_int(x.rsplit('_', 1)[0])
                            for x in glob(pristine + '_*')])
                d = pristine + '_%d' % (last + 1)
            else:
                d = pristine + '_1'
        else:
            d = pristine
        return d

    def reconstructCases(self, cases):
        for case in cases:
            Runner(args=["reconstructPar" ,"-latestTime", "-case" ,case])

    def sampleDictionaries(self, cases, work, wind_dict):
        # TODO - at the moment for 90 degrees phi only and in line instead of in a function
        for case in cases:
            self._r.status('preparing Sample file for case '+case.name)
            sampleFile = ParsedParameterFile(path.join(case.systemDir(), "sampleDict"))
            del sampleFile.content['sets'][:]
            if len(wind_dict["Measurements"]) > 0:
                self._r.status("creating sample locations for measurements")
                for metMast in wind_dict["Measurements"]:
                    self._r.status("adding met mast " + metMast)
                    # creating sub directory entry
                    sampleFile.content['sets'].append(metMast)
                    # creating another fictional sub directory entry - so that i can run it over in a second
                    sampleFile.content['sets'].append([metMast])
                    sampleFile['sets'][len(sampleFile['sets'])-1] = \
                    {'type':'uniform', 'axis':'z',\
                    'start':'('+str(wind_dict["Measurements"][metMast]["x"])+" "\
                               +str(wind_dict["Measurements"][metMast]["y"])+" "\
                               +str(wind_dict["Measurements"][metMast]["gl"])+")",\
                    'end':  '('+str(wind_dict["Measurements"][metMast]["x"])+" "\
                               +str(wind_dict["Measurements"][metMast]["y"])+" "\
                               +str(wind_dict["Measurements"][metMast]["gl"]+\
                                    wind_dict["Measurements"][metMast]["h"])+")",\
                    'nPoints':wind_dict['sampleParams']['nPoints']}
            if len(wind_dict['sampleParams']['metMasts'])>0:
               self._r.status("creating sample locations for sampleParams")
               for metMast in wind_dict['sampleParams']['metMasts']:
                    # creating sub directory entry
                    sampleFile.content['sets'].append(metMast)
                    # creating another fictional sub directory entry - so that i can run it over in a second
                    sampleFile.content['sets'].append([metMast])
                    sampleFile['sets'][len(sampleFile['sets'])-1] = \
                    {'type':'uniform', 'axis':'z',\
                    'start':'('+str(wind_dict["sampleParams"]["metMasts"][metMast]["x"])+" "\
                               +str(wind_dict["sampleParams"]["metMasts"][metMast]["y"])+" "\
                               +str(wind_dict["sampleParams"]["metMasts"][metMast]["gl"])+")",\
                    'end':  '('+str(wind_dict["sampleParams"]["metMasts"][metMast]["x"])+" "\
                               +str(wind_dict["sampleParams"]["metMasts"][metMast]["y"])+" "\
                               +str(wind_dict["sampleParams"]["metMasts"][metMast]["gl"]+\
                                    wind_dict["sampleParams"]["metMasts"][metMast]["h"])+")",\
                    'nPoints':wind_dict['sampleParams']['nPoints']}

            del sampleFile.content['surfaces'][:]
            for i,h in enumerate(wind_dict['sampleParams']['hSample']):
                self._r.status('preparing sampling surface at '+str(h)+' meters agl')
                translateSTL.stl_shift_z_filenames(path.join(case.name,'constant/triSurface/terrain.stl'), path.join(case.name,'constant/triSurface/terrain_agl_'+str(h)+'.stl'), h)
                # creating sub directory entry
                sampleFile.content['surfaces'].append('agl_'+str(h))
                # creating another fictional sub directory entry - so that i can run it over in a second
                sampleFile.content['surfaces'].append(['agl_'+str(h)])
                sampleFile['surfaces'][len(sampleFile['surfaces'])-1]={'type':'sampledTriSurfaceMesh','surface':'terrain_agl_'+str(h)+'.stl','source':'cells'}
            sampleFile.writeFile()
            self._r.status('Sampling case '+case.name)
            Runner(args=["sample" ,"-latestTime", "-case" ,case.name])


    def writeMetMastLocations(self, case): # will replace the following 4 lines
        print 'TODO writeMetMastLocations'

    def calcHitRate(self, cases, pdf, wind_dict):
        print "TODO calcHitRate"

    def newFigure(self, *args, **kw):
        fig = plt.figure(self._fig_n, *args, **kw)
        self._fig_n += 1
        return fig

    def save_svg(self, fig_name, f):
        if self._plots != 'svg':
            return
        filename = fig_name + '.svg'
        f.savefig(filename)
        self._r.status('PLOT %s' % filename)

    def plotContourMaps(self, cases, pdf, wind_dict):
        refinement_length = wind_dict['SHMParams']['domainSize']['refinement_length']
        xi = linspace(-refinement_length,refinement_length,wind_dict['sampleParams']['Nx'])
        yi = xi
        xmesh, ymesh = meshgrid(xi, yi)
        hs = wind_dict['sampleParams']['hSample']
        avgV = zeros((len(hs), len(xi), len(yi)))
        plt = self._r.plot
        for i, case in enumerate(cases):
            lastTime = genfromtxt(path.join(case.name,'PyFoamState.CurrentTime'))
            for hi, h in enumerate(hs):
                data = genfromtxt(path.join(case.name,'surfaces/'+str(int(lastTime))+'/U_agl_'+str(h)+'.raw'))
                # after a long trial and error - matplotlib griddata is shaky and crashes on some grids. scipy.interpolate works on every grid i tested so far
                vi = sc.griddata((data[:,0].ravel(),data[:,1].ravel()), (data[:,3].ravel()**2+data[:,4].ravel()**2)**0.5, (xmesh,ymesh))
                ax = self.newFigure()
                plt.title(case.name+'\n at height '+str(h)+' meter agl')
                CS = plt.contourf(xi, yi, vi, 400,cmap=plt.cm.jet,linewidths=0)
                plt.colorbar(CS)
                pdf.savefig()
                self.save_svg(os.path.join(case.name, 'contour'), ax.figure)
                # assuming the windDir weights are normalized
                #import pdb; pdb.set_trace()
                avgV[hi, :, :] += vi * wind_dict["caseTypes"]["windRose"]["windDir"][i][0]
        for hi, h in enumerate(hs):
            ax = self.newFigure()
            plt.title('average wind velocity at height ' + str(h) + ' meter agl')
            CS = plt.contourf(xi, yi, avgV[hi, :, :], 400, cmap=plt.cm.jet, linewidths=0)
            plt.colorbar(CS)
            pdf.savefig()
            self.save_svg('average_wind_velocity_h_%s' % str(h), ax.figure)

    def plot_initial_wind_rose(self, wind_dict, params):
        #windrose like a stacked histogram with normed (displayed in percent) results
        ax = self.initial_wind_rose_axes()
        weight = [x[0] for x in wind_dict['caseTypes']['windRose']['windDir'][:]]
        wd = [x[1] for x in wind_dict['caseTypes']['windRose']['windDir'][:]]
        ws = [x[-1] for x in wind_dict['caseTypes']['windRose']['windDir'][:]]
        (wd, ws) = hist_to_time(weight, (wd, ws))
        ax.bar(wd, ws, normed=True, opening=0.8, edgecolor='white')
        self.initial_wind_rose_legend(ax)
        # TODO: add save_svg to windrose
        #self.save_svg('initial_wind_rose_axes', ax.figure)

    def run_windpyfoam(self, dict):
        """
        Mesh: creating the write snappyHexMeshDict file
        use the right snappyHexMeshDict_XXX.template file with wind_dict
        but --> already at this stage i have to work in a loop according to the
        amount of cases i am asked to solve. each case will be cloned from the
        template case, and then the procedure of
        if doing grid convergance with a single
        foreach dir in {winddirs, grid}:
            1. creating snappyHexMeshDict and blockMeshdict according to flow direction and other parameters
            2. creating the blockMesh
            3. decomposing the domain
            4. creating the snappyHexMesh - running in parallel (sfoam.py or not - depending on user input)
            5. decomposing the created mesh
            6. running pyFoamRunner.py through sfoam (or not - depending on user input)

        After all cases stop running
        7. if exist (usually) - reading real measurements
        8. creating sampleDict according to measurement locations and user input
            (which asks for wind speed contour map at certain height above ground)
        9. sampling (command is "sample")
        10. using the results to calculate the following metrics
            1. for a specific grid size and multiple directions and weights for
            each direction - the power density and average wind speed averaged over
            the direction at specific heights above ground level
            2. for a specific direction and different grid cell sizes - the grid
            error according to some known grid convergence algorithm
            3. a "hit rate" which shows the aggreement of the simulated wind speeds
            and turbulence to the measurements
        """
        if not os.path.exists(dict):
            self._r.error("missing %s file" % dict)
            raise SystemExit
        try:
            wind_dict = ParsedParameterFile(dict)
        except Exception, e:
            self._r.error("failed to parse windPyFoam parameter file:")
            self._r.error(str(e))
            raise SystemExit
        wind_dict['runs'] = self.run_directory('runs')

        # starting the pdf file for accumilating graphical results
        pdf = PdfPages('results.pdf')

        # preparing the grid, bc and ic for all cases
        gen = []
        if wind_dict["caseTypes"]["gridConvergence"]:
            gen = self.grid_convergance_params_generator(wind_dict)
        gen = itertools.chain(gen,
                self.wind_rose_params_generator(wind_dict))
        cases = []
        names = []

        for params in gen:
            self._r.debug(params['name'])
            work = self.create_case(wind_dict, params)
            names.append('wind%s' % int(180 / pi * params['phi']))
            cases.append(work)

        # plotting initial wind rose
        pdf2 = PdfPages('initialWindRose.pdf')
        self.plot_initial_wind_rose(wind_dict, params)
        pdf2.savefig()
        pdf2.close()
        os.system('xdg-open initialWindRose.pdf')

        self._r.status('RUNNING CASES')
        runArg = read_dict_string(wind_dict, 'runArg')
        self._r.status(runArg)
        assert(runArg in ['Runner', 'plotRunner', 'sfoam'])
        runCases(names=names,
                 n=wind_dict['procnr'], runArg=runArg,
                 cases=[case.name for case in cases])
        self._r.status('DONE running cases')
        # reconstructing case
        self._r.status('Reconstructing cases')
        self.reconstructCases([case.name for case in cases])

        self._r.status('Building sample dictionaries')
        self.sampleDictionaries(cases, work, wind_dict)

        self._r.status('Ploting hit-rate')
        self.calcHitRate(cases, pdf, wind_dict)

        self._r.status('Ploting contour maps at specified heights')
        self.plotContourMaps(cases, pdf, wind_dict)
        # TODO
        self._r.status('plotting wind rose and histogram at specified location')
        # TODO
        pdf.close()
        self._r.status('results.pdf')
        if self._plots == 'gui':
            self._r.plot.show()
        self._r.status('exiting')

def run_windpyfoam(reporter, dict, plots):
    solver = Solver(reporter, plots=plots)
    solver.run_windpyfoam(dict)

## Tests

def test_plot_initial_wind_rose():
    stdio = __import__('stdio')
    winddict = ParsedParameterFile('windPyFoamDict')
    solver = Solver(stdio, True)
    solver.plot_initial_wind_rose(winddict, {})
    stdio.plot.show()

def test_plot_contour_maps():
    pdf = PdfPages('test_contour.pdf')
    stdio = __import__('stdio')
    wind_dict = ParsedParameterFile('windPyFoamDict')
    solver = Solver(stdio, plots='svg')
    class FakeCase(object):
        def __init__(self, name):
            self.name = name
    cases = [FakeCase(name='runs_20121215_122648/test_template_rose_270/')]
    solver.plotContourMaps(cases, pdf, wind_dict)
    stdio.plot.show()

if __name__ == '__main__':
    test_plot_contour_maps()
