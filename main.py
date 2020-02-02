import subprocess
import os
import json
import sys
import re
from enum import Enum
from urllib import parse

'''
All paths here, excepting `buildDir` and logName,
are relative to script directory.
`buildDir` is relative to source code directory.
`logName` is relative to executable directory.
'''

base = ''

testAddr = 'https://github.com/kystyn/paper_test_source.git'
testDir = 'test'

studentDir = 'student'
studentAnswersFileName = 'answers.txt'
referenceAnswersFileName = 'refAnswers.txt'

buildDir = 'build'

generatorCMakeParam = 'Ninja'
generator = 'ninja'

packageName = 'test'

jsonFile = 'results.json'

branch = 'master'

trashMarker = 'xxx'


class ComparisonStatus(Enum):
    OK = 1
    REDUNDANT = 2
    MISSING = 3
    WRONG_PLACE = 4


def run(command, sendException=True):
    status = subprocess.run([command], shell=True)
    if status.returncode != 0 and sendException:
        raise RuntimeError


'''
Update (or init, if wasn't) repository function.
ARGUMENTS:
    - git repository address:
        repoAddress
    - local directory name to pull
      (relatively to script path):
        repoDir
RETURNS: None
'''


def updateRepo(repoAddress, repoDir, revision=''):
    global base
    if not os.path.exists(repoDir):
        os.mkdir(repoDir)
        os.chdir(repoDir)
        run("git init")
        run("git remote add origin " + repoAddress)
    else:
        os.chdir(repoDir)
    run("git pull origin " + branch)
    run("git checkout " + revision)
    os.chdir(base)


# root and is relative to current file
'''
Build code with cmake function.
ARGUMENTS:
    - directory with sources
    (relatively to script path):
        root
    - target for executable
    (relatively to script path):
        target
RETURNS:
    return code of build
'''
def build(root, target):
    global base
    os.chdir(root)
    if not os.path.exists(target):
        os.mkdir(target)
    run("cmake -B " + target + " -G " + generatorCMakeParam)

    os.chdir(target)
    subprocess.run(generator)
    os.chdir(base)


'''
Run test code function from testDir/buildDir.
ARGUMENTS: None.
RETURNS: None.
'''
def runTests():
    global base
    os.chdir(testDir)

    # get project name

    cmakefile = open('CMakeLists.txt', 'r')

    projname = str()
    for s in cmakefile:
        idx = s.find('project')
        if idx != -1:
            projname = s[idx + 8: s.find(')')]
            break

    os.chdir(buildDir)
    run('./' + projname + ' > ' + referenceAnswersFileName)

    os.chdir(base)


'''
Stash changes in the test and student repo function.
ARGUMENTS: None
RETURNS: None
'''


def clear():
    global base
    if os.path.exists(base + '/' + studentDir):
        os.chdir(base + '/' + studentDir)
        run("git stash")
    if os.path.exists(base + '/' + testDir):
        os.chdir(base + '/' + testDir)
        run("git stash")
    os.chdir(base)


def findEndOfCurStringOutput(idx, lines):
    newIdx = -1
    for i in range(idx, len(lines)):
        res = re.match('\d*:', lines[i])
        if res is not None:
            newIdx = i
            break
    return newIdx


def compareAnswers():
    studentAnswers = open(studentDir + '/' + studentAnswersFileName, 'r')
    referenceAnswers = open(testDir + '/' + buildDir + '/' + referenceAnswersFileName, 'r')

    studLines = []
    for l in studentAnswers:
        studLines.append(l)

    refLines = []
    for l in referenceAnswers:
        refLines.append(l)

    refIdx = 0
    studIdx = 0

    # key - string number
    # value - dictionary of:
    #       key - OK/REDUNDANT/MISSING, value - count
    outputOf = {}

    while 0 <= refIdx < len(refLines):
        res = re.match('\d*:', refLines[refIdx])
        if res is not None:
            refIdx += 1
            studIdx += 1
            found = False
            # find such string in student answer
            for i in range(studIdx, len(studLines)):
                if studLines[i] == refLines[refIdx] or studLines[i] == trashMarker + '\n':
                    if studLines[i] == trashMarker + '\n' and not abs(int(refLines[refIdx])) > 1000:
                        continue
                    found = True
                    studIdx = i
                    break

            # detect area of output for current string
            newRefIdx = findEndOfCurStringOutput(refIdx, refLines)
            if newRefIdx == -1:
                newRefIdx = len(refLines)

            missing = 0
            redundant = 0
            wrong_place = 0
            ok = 0

            # write into result
            if not found:
                missing = newRefIdx - refIdx
            else:
                studStart = studIdx

                newStudIdx = findEndOfCurStringOutput(studIdx, studLines)
                if newStudIdx == -1:
                    newStudIdx = len(studLines)

                visitedStudentStrings = []
                for i in range(refIdx, newRefIdx):
                    found = False
                    for j in range(studIdx, newStudIdx):
                        if studLines[j] == refLines[i] or studLines[j] == trashMarker + '\n':
                            if studLines[j] == trashMarker + '\n' and not abs(int(refLines[i])) > 1000:
                                continue
                            visitedStudentStrings.append(j)
                            found = True
                            ok += 1
                            studIdx = j
                            break
                    if not found:
                        missing += 1

                if ok != newRefIdx - refIdx:
                    # run over student strings
                    # if no such string in reference => redundant. else - wrong place
                    for i in range(studStart, newStudIdx):
                        try:
                            idx = refLines.index(studLines[i], refIdx, newRefIdx)
                            if idx not in visitedStudentStrings:
                                wrong_place += 1
                        except ValueError:
                            redundant += 1

            outputOf.update(
                {
                    refLines[refIdx - 1][0: len(refLines[refIdx - 1]) - 2]:
                        {
                            ComparisonStatus.OK: ok,
                            ComparisonStatus.REDUNDANT: redundant,
                            ComparisonStatus.MISSING: missing,
                            ComparisonStatus.WRONG_PLACE: wrong_place
                        }
                })
            refIdx = newRefIdx
    return outputOf


'''
Generate output JSON file function.
ARGUMENTS:
    - file to output:
        fileName
    - parse result from `parseLog` function:
        parseRes
RETURNS: None
'''

def genJson(fileName, parseRes):
    global base
    outJson = {"data": []}
    outF = open(fileName, 'wt')

    curTagName = 'Normal'
    for key in parseRes:
        curTestName = key
        condition = \
            parseRes[key][ComparisonStatus.REDUNDANT] == 0 and \
            parseRes[key][ComparisonStatus.WRONG_PLACE] == 0 and \
            parseRes[key][ComparisonStatus.MISSING] == 0
        strg = {
            "packageName": packageName,
            "methodName": curTestName,
            "tags": [curTagName],
            "results": [{
                "status": "SUCCESSFUL" if condition else "FAILED",
                "failure": {
                    "@class": "org.jetbrains.research.runner.data.UnknownFailureDatum",
                    "nestedException":
                        "Redundant: " + str(parseRes[key][ComparisonStatus.REDUNDANT]) + ", wrong place: " +
                        str(parseRes[key][ComparisonStatus.WRONG_PLACE]) + ", missing:" +
                        str(parseRes[key][ComparisonStatus.MISSING]) + ", ok: " + str(parseRes[key][ComparisonStatus.OK])
                } if not condition else None
            }]
        }
        outJson['data'].append(strg)
    outF.write(json.dumps(outJson, indent=4))
    outF.close()


'''
Main program function.
ARGUMENTS: None.
RETURNS:
    0 if success,
    1 if failed compilation.
'''


def main():
    global base
    try:
        base = os.path.abspath(os.curdir)
        updateRepo(testAddr, testDir)
        if "-src" not in sys.argv:
            raise RuntimeError
        studentAddr = sys.argv[sys.argv.index("-src") + 1]
        if "-v" in sys.argv:
            num = sys.argv.index("-v");
            updateRepo(studentAddr, studentDir, sys.argv[num + 1])
        else:
            updateRepo(studentAddr, studentDir)

        build(testDir, buildDir)
        runTests()
        genJson(jsonFile, compareAnswers())
        clear()
    except:  # RuntimeError:
        print('Exception caught ')
        clear()
        run('rm -rf ' + base + '/' + studentDir + ' ' + base + '/' + testDir)
        return 1
    return 0


main()