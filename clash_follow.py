#!/bin/env python
# clash_follow.py
# Analyze distances of discovered collisions over time

from argparse import ArgumentParser
from numpy import array, dot, sqrt
from collections import namedtuple
from clash_screen import selectFrames
from shared import *

__author__ = 'Charles'

Atom = namedtuple('Atom', ['ID', 'coords'])
Clash = namedtuple('Clash', ['res1', 'res2'])
Frame = namedtuple('Frame', ['frameID', 'RMSD'])
Transition = namedtuple('Transition', ['clash', 'type', 'chosenFrame', 'atoms', 'allFR'])
FrameResult = namedtuple('FrameResult', ['frame', 'dist', 'atoms'])


def main():
    # Process global variables and paths
    parse()
    global WORKDIR
    WORKDIR = os.getcwd()
    global FRAMESPATH
    if args.frames is not None and not os.path.isabs(args.frames):
        FRAMESPATH = WORKDIR + "/" + args.frames
    else:
        FRAMESPATH = args.frames
    if not os.path.isdir(FRAMESPATH):
        os.mkdir(FRAMESPATH)
    global DISTPATH
    if args.dist is not None and not os.path.isabs(args.dist):
        DISTPATH = WORKDIR + "/" + args.dist
    else:
        DISTPATH = args.dist
    if args.collisions is not None and not os.path.isabs(args.collisions):
        COLLISIONSPATH = WORKDIR + "/" + args.collisions
    else:
        COLLISIONSPATH = args.collisions
    global MIN
    global MAX
    if args.min is None:
        MIN = 0
    else:
        MIN = args.min
    if args.max is None:
        MAX = sys.maxint
    else:
        MAX = args.max

    # Establish sets of collisions per type and read data
    TtoN, CtoT, CtoN = set(), set(), set()
    with open(COLLISIONSPATH) as collisionsFile:
        for line in collisionsFile:
            transitionList = line.split()
            t = (int(transitionList[1]), int(transitionList[2]))
            if line.startswith("TN"):
                TtoN.add(Clash(min(t), max(t)))
            elif line.startswith("CT"):
                CtoT.add(Clash(min(t), max(t)))
            elif line.startswith("CN"):
                CtoN.add(Clash(min(t), max(t)))
    TtoN, CtoT, CtoN = [sorted(list(s), key=lambda x: (x.res1, x.res2)) for s in (TtoN, CtoT, CtoN)]

    # Read the distance file
    with open(DISTPATH) as distFile:
        frames = [Frame(int(line.split()[0]), float(line.split()[1])) for line in distFile]

    if not args.check_all:
        frameList = selectFrames(frames, MIN, MAX, args.freq)
    else:
        frameList = frames[0::args.freq]
    totalFrames = len(frameList)

    # Set of all clashes, with three sublists sorted
    clashes = TtoN + CtoT + CtoN  # list of tuples
    TtoNcount, CtoTcount, CtoNcount = [len(s) for s in (TtoN, CtoT, CtoN)]
    totalClashes = TtoNcount + CtoTcount + CtoNcount
    log("Processing %i collisions\n" % totalClashes)

    # Find distances for each collision at different frames
    # Iterate over the frames to read residues
    log("Reading frame data.\n")
    frameResData = {}  # {Frame: residues, ...}
    resNames = {}

    for count, frame in enumerate(frameList):
        log("\rFrame %i of %i" % (count + 1, totalFrames))
        with open(FRAMESPATH + "/%i.pdb" % frame.frameID) as pdb:
            # Read frame file into the residues dictionary
            residues = {}  # {residueID: [Atom, ...], ...}
            for line in pdb:
                if line[0:4] != "ATOM" or line[17:20] not in RESIDUES:
                    continue
                vals = line.split()
                resID = int(vals[4])
                atomID = int(vals[1])
                if resID not in residues or residues[resID] is None:
                    residues[resID] = []
                atomCoords = array([float(line[(30 + f * 8):(38 + f * 8)]) for f in range(3)])
                resName = vals[3]  # three-letter name of residue
                if resID not in resNames or resNames[resID] is None:
                    resNames[resID] = resName
                residues[resID].append(Atom(atomID, atomCoords))
            frameResData[frame] = residues
    log("\n")
    # Iterate over the collisions to check each frame
    log("Checking collisions.\n")

    def checkClash(clashID):
        """Returns a string representing the type and ID of the clash followed by the
        appropriate last frameID and RMSD and atoms/distance."""
        printed = "Transition %i of %i " % (clashID + 1, totalClashes)
        clash = clashes[clashID]
        # Iterate over each stored frame
        frameResults = []  # [(frame, dist, atoms), ...]
        for fr, frResidues in frameResData.iteritems():
            # find minimum distance between residues
            minDist = sys.maxint
            minAtoms = (0, 0)
            for a1, coord1 in frResidues[clash.res1]:
                for a2, coord2 in frResidues[clash.res2]:
                    diff = coord1 - coord2
                    thisDist = sqrt(dot(diff, diff))
                    if thisDist < minDist:
                        minDist = thisDist
                        minAtoms = a1, a2
            # Add the minimum distance for this clash
            frameResults.append(FrameResult(fr, minDist, minAtoms))

        # Determine which frame to keep
        if clashID < TtoNcount:
            # T->N: print last positive collision
            for fr, distance, atoms in reversed(frameResults):  # go backwards
                if distance < args.thres:  # clash exists
                    printed += "%i,%i TN %i %.3f " % (clash.res1, clash.res2, fr.frameID, fr.RMSD) + str(atoms) + "\n"
                    log(printed)
                    return Transition(clash, "TN", fr, atoms, frameResults)
        elif clashID < TtoNcount + CtoTcount:
            # C->T: print first negative collision
            for fr, distance, atoms in frameResults:
                if distance > args.thres:  # no longer exists
                    printed += "%i,%i CT %i %.3f " % (clash.res1, clash.res2, fr.frameID, fr.RMSD) + str(atoms) + "\n"
                    log(printed)
                    return Transition(clash, "CT", fr, atoms, frameResults)
        else:
            # C->N: print first negative collision
            for fr, distance, atoms in frameResults:
                if distance > args.thres:  # no longer exists
                    printed += "%i,%i CN %i %.3f " % (clash.res1, clash.res2, fr.frameID, fr.RMSD) + str(atoms) + "\n"
                    log(printed)
                    return Transition(clash, "CN", fr, atoms, frameResults)

    output = parMap(checkClash, range(len(clashes)), n=args.processes, silent=True)
    if None in output:
        log(YELLOW + UNDERLINE + "Warning:" + END
            + " %i transitions not found in frames. --freq may have changed from clash_check"
              " or the transition may occur out of range.\n" % output.count(None))
    output = [o for o in output if o is not None]

    # write output
    # sort by type, then by RMSD, then by frameID, then by clash

    out = sorted([section for section in output if section is not None],
                 key=lambda j: (j.type, j.chosenFrame.RMSD, j.chosenFrame.frameID, j.clash))
    sys.stdout.write("# type resname1 res1 atom1 resname2 res2 atom2 frameID RMSD\n")
    sys.stdout.flush()
    for (res1, res2), clashType, frame, (atom1, atom2), allFR in out:
        sys.stdout.write("%s %s %i %i %s %i %i %i %.3f\n" % (clashType, resNames[res1], res1, atom1,
                                                             resNames[res2], res2, atom2, frame.frameID, frame.RMSD))
    sys.stdout.flush()

    if args.plotfile is not None:

        def partition(c, i):
            """Separate the input list into two lists based on the condition"""
            tl = []
            fl = []
            for k in i:
                if c(k):
                    tl.append(k)
                else:
                    fl.append(k)
            return tl, fl

        # Separate based on type and whether it exceeds the minimum threshold at max distance
        (CNlow, CN), (CTlow, CT), (TNlow, TN) = [partition(
            lambda v: max([u.dist for u in v.allFR]) < args.minthres,
            [o for o in out if o.type == y]) for y in ("CN", "CT", "TN")]

        # Sort based on max distance
        (CNlow, CN, CTlow, CT, TNlow, TN) = [sorted(q, key=lambda v: max([w.dist for w in v.allFR]), reverse=True)
                                             for q in (CNlow, CN, CTlow, CT, TNlow, TN)]

        plotArguments = ((out, "", "All"),
                         (CN, "CN", "Conserved to nonexistent"), (CNlow, "CNlow", "Conserved to nonexistent (low)"),
                         (CT, "CT", "Conserved to transitory"), (CTlow, "CTlow", "Conserved to transitory (low)"),
                         (TN, "TN", "Transitory to nonexistent"), (TNlow, "TNlow", "Transitory to nonexistent (low)"))
        plotArguments = [t for t in plotArguments if len(t[0]) > 0]  # exclude empty categories

        def chunks(e, k):
            """Yield successive k-sized chunks from e."""
            for p in xrange(0, len(e), k):
                yield e[p:p + k]

        maxDist = int(5 * round(float(max([max([d.dist for d in o.allFR]) for o in out])) / 5))
        # maximum reached distance rounded to 5

        for transitionList, name, fullName in plotArguments:
            # Write gnuplot data
            plotData = {}  # {RMSD: dists, ...}
            for transition in transitionList:
                for frameResult in transition.allFR:
                    if frameResult.frame.RMSD not in plotData or plotData[frameResult.frame.RMSD] is None:
                        plotData[frameResult.frame.RMSD] = []
                    plotData[frameResult.frame.RMSD].append(frameResult.dist)
            # Remove sections with excess data; this occurs with frames that have repeated RMSD
            plotDataList = []
            for item in sorted(plotData.iteritems(), key=itemgetter(0)):
                if len(item[1]) == len(transitionList):
                    plotDataList.append(item)
            with open(args.plotfile + name, 'w') as plot:
                # write header
                plot.write("RMSD ")
                for transition in transitionList:
                    plot.write("%i/%i " % (transition.clash.res1, transition.clash.res2))
                plot.write("\n")
                # write rows
                for frame in plotDataList:
                    # write header column of RMSD
                    plot.write("%.3f " % frame[0])
                    for dist in frame[1]:
                        # write each distance
                        plot.write("%.3f " % dist)
                    plot.write("\n")

            # write gnuplot scripts
            # Split the list into chunks
            lastID = 0
            chunksize = args.max_plot
            if name == "":
                chunksize = sys.maxint  # this is the "all" section, no need to chunk
            for section, chunk in enumerate(list(chunks(transitionList, chunksize))):
                # write a file for gnuplot commands
                fileName = "gnuplot%s_%i.sh" % (name, section)
                with open(fileName, 'w') as gnuplot:
                    gnuplot.write("""echo "
set term png
set output 'gnuplot%s_%i.png'
""" % (name, section))
                    if name == "":
                        gnuplot.write("""set title '%s collisions'
set nokey
""" % fullName)
                    else:
                        gnuplot.write("""set title '%s collisions part %i'
set key autotitle columnhead outside vertical right top maxcols 1
""" % (fullName, section + 1))
                    gnuplot.write("""set ylabel 'Distance (angstroms)'
set xlabel 'RMSD (angstroms)'
set yrange [0:%i]
set xrange [0:*] reverse
""" % maxDist)
                    if MIN is not None and MIN > frameList[-1].RMSD:
                        gnuplot.write("""set arrow from %i,0 to %i,%i nohead lc rgb 'black'
""" % (MIN, MIN, maxDist))
                    if MAX is not None and MAX < frameList[0].RMSD:
                        gnuplot.write("""set arrow from %i,0 to %i,%i nohead lc rgb 'black'
""" % (MAX, MAX, maxDist))
                    gnuplot.write("""plot '%s' using 1:%i w l, """ % (args.plotfile + name, lastID + 2))
                    # for each column
                    for col in xrange(len(chunk) - 1):
                        gnuplot.write(" '' using 1:%i w l" % (col + 3 + lastID))
                        # comma if not last
                        if col < len(chunk) - 2:
                            gnuplot.write(", ")
                    lastID += len(chunk)

                    # end the script
                    gnuplot.write("""
" | gnuplot -persist
""")
        # make executable
        system("chmod +x gnuplot*.sh")


def parse():
    """Parse command-line arguments"""
    parser = ArgumentParser(description="Plot distances of discovered collisions over time")
    parser.add_argument('-f', "--frames", help="folder containing PDBs of frames", type=str,
                        action=FullPath, default="trajectory")
    parser.add_argument('-d', "--dist", help="two column frame/distance file", type=str,
                        action=FullPath, default="distances")
    parser.add_argument("--min", help="start of distance range", type=float, default=0)
    parser.add_argument("--max", help="end of distance range", type=float, default=sys.maxint)
    parser.add_argument("--check_all", help="follow the collision for the whole trajectory but mark at min and max", 
                        action="store_true")
    parser.add_argument("--freq", help="only keep every n frames (default is 1 for all frames)",
                        type=int, default=1)
    parser.add_argument("--outfreq", help="same as freq, but for distance output", type=int, default=1)
    parser.add_argument("--max_plot", help="maximum number of collisions per plot (default is 8)",
                        type=int, default=8)
    parser.add_argument('-t', "--thres", help="collision threshold in angstroms (default is 4)",
                        type=float, default=4.)
    parser.add_argument("--minthres", help="separate collisions that never go above this distance (default is 10)",
                        type=float, default=10.)
    parser.add_argument('-c', "--collisions", help="list of collisions "
                                                   "from clash_check", type=str, action=FullPath, default="check")
    parser.add_argument('--plotfile', help="output file prefix for gnuplot", type=str, action=FullPath, default="plot")
    parser.add_argument('-p', "--processes", help="maximum number of processes (default is half cpu count)", type=int,
                        default=cpu_count() / 2)
    global args
    args = parser.parse_args()


if __name__ == "__main__":
    main()
