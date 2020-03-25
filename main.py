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
    WAS_FOUND = 5


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
    for i in range(idx + 1, len(lines)):
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
            found = False

            # find such string in student answer
            for i in range(studIdx, len(studLines)):
                if studLines[i].replace(' ', '') == refLines[refIdx].replace(' ', '') or studLines[i] == trashMarker + '\n':
                    if studLines[i] == trashMarker + '\n' and not abs(int(refLines[refIdx])) > 1000:
                        continue
                    found = True
                    studIdx = i
                    break


            # detect area of output for current string
            newRefIdx = findEndOfCurStringOutput(refIdx, refLines)
            if newRefIdx == -1:
                newRefIdx = len(refLines)

            refIdx += 1

            missing = 0
            redundant = 0
            wrong_place = 0
            ok = 0
            newStudIdx = studIdx

            # write into result
            if not found:
                missing = newRefIdx - refIdx
            else:
                newStudIdx = findEndOfCurStringOutput(studIdx, studLines)
                if newStudIdx == -1:
                    newStudIdx = len(studLines)

                studIdx += 1

                visitedStudentStrings = []
                for i in range(refIdx, newRefIdx):
                    found = False
                    for j in range(studIdx, newStudIdx):
                        if (studLines[j].replace(' ', '') == refLines[i].replace(' ', '')  or studLines[j] == trashMarker + '\n') \
                                and j not in visitedStudentStrings:
                            if studLines[j] == trashMarker + '\n' and not abs(int(refLines[i])) > 1000:
                                continue
                            if (len(visitedStudentStrings) > 0 and j > max(visitedStudentStrings)) \
                                    or len(visitedStudentStrings) == 0:
                                ok += 1
                            else:
                                wrong_place += 1
                            visitedStudentStrings.append(j)
                            found = True
                            break
                    if not found:
                        missing += 1

                # student written OK, WRONG_PLACE and redundant/wrong lines
                redundant = newStudIdx - studIdx - ok - wrong_place

            outputOf.update(
                {
                    refLines[refIdx - 1][0: len(refLines[refIdx - 1]) - 2]:
                        {
                            ComparisonStatus.OK: ok,
                            ComparisonStatus.REDUNDANT: redundant,
                            ComparisonStatus.MISSING: missing,
                            ComparisonStatus.WRONG_PLACE: wrong_place,
                            ComparisonStatus.WAS_FOUND: found
                        }
                })
            refIdx = newRefIdx
            studIdx = newStudIdx
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
            parseRes[key][ComparisonStatus.MISSING] == 0 and \
            parseRes[key][ComparisonStatus.WAS_FOUND] is True
        strg = {
            "packageName": packageName,
            "methodName": curTestName,
            "tags": [curTagName],
            "results": [{
                "status": "SUCCESSFUL" if condition else "FAILED",
                "failure": {
                    "@class": "org.jetbrains.research.runner.data.UnknownFailureDatum",
                    "nestedException":
                        "Redundant: " + str(parseRes[key][ComparisonStatus.REDUNDANT]) + ", wrong order/wrong answer: " +
                        str(parseRes[key][ComparisonStatus.WRONG_PLACE]) + ", missing:" +
                        str(parseRes[key][ComparisonStatus.MISSING]) + ", ok: " + str(parseRes[key][ComparisonStatus.OK]) +
                        ("" if parseRes[key][ComparisonStatus.WAS_FOUND] else ", not found")
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

        if "-src" not in sys.argv:
            raise RuntimeError

        testAddr = sys.argv[sys.argv.index("-src") + 1]
        if "-vSrc" in sys.argv:
            num = sys.argv.index("-vSrc");
            updateRepo(testAddr, testDir, sys.argv[num + 1])
        else:
            updateRepo(testAddr, testDir)

        if "-ans" not in sys.argv:
            raise RuntimeError
        studentAddr = sys.argv[sys.argv.index("-ans") + 1]
        if "-vAns" in sys.argv:
            num = sys.argv.index("-vAns");
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
