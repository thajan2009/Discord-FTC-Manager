"""FTC HELP DIRECTORY — OWNER EDIT ZONE.

How to add, change or remove an entry:
    1. Each entry is one line:  "trigger": "Response text shown in Discord",
       (note the comma at the end of every line except the last one).
    2. Trigger = what people type WITHOUT the "!". Lowercase, one word, no spaces.
       Example: "axon" makes !axon work everywhere the bot is.
    3. Response = plain text or links, exactly as you want it posted.
    4. Save the file and restart the bot (Bot-hosting.net: Files -> edit ->
       save -> Restart). No database or website changes needed.

Order of replies when several dictionaries match:
    server custom command (!addcmd)  >  this FTC directory  >  global commands.
So a server can override any entry below with !addcmd <same name> <own text>.

Type !ftchelp in Discord to browse everything defined here.
"""

FTCHELP: dict[str, str] = {
    "axon": "https://axon-robotics.com/ \n https://discord.com/channels/1443377051305508896/1443405548891541624/1444419347283050667 - Technical Drawings\n https://discord.com/channels/1443377051305508896/1443405548891541624/1490495685299146762 - STEP Files",
    "mastersketch": "<https://youtu.be/myHrTdh2AOg>",
    "featurescripts": "[FTCDesign Featurescripts](<https://cad.onshape.com/documents/97721efb7fbf764743af6da4/>) \n[General featurescripts](<https://github.com/dcowden/featurescript>) \n[Belt Gen](<https://cad.onshape.com/documents/c163c756b5096bcd95e5692a>) \n[Pulley Gen](<https://cad.onshape.com/documents/a116695750b054564ac11cbb/w/2025d9645023834db075348e/e/87987a3f29f6075a645ceb7b>) \n[Wheel Gen](<https://cad.onshape.com/documents/7ad7ca50c381036492cab695>) \n[Spool Gen](<https://cad.onshape.com/documents/761024cb69916ef24796adf4>) \n[Gear Gen](<https://cad.onshape.com/documents/f349bdd78c53f3325055aefc>) \n[Open Source Flop](<https://linktr.ee/openflap_openmold>) \n[Open Source Intake Tubing](<https://github.com/Hudson-1/opLibrary/tree/main/opTake>) \n[Open Source Misumi Slides](<https://cad.onshape.com/documents/f733a4dbb62b9d5ad77ce67c>) \n[Open Source Misumi Inserts](<https://github.com/Hudson-1/opLibrary/tree/main/opInsert>)",
    "pulleygen": "<https://cad.onshape.com/documents/a116695750b054564ac11cbb/w/2025d9645023834db075348e/e/87987a3f29f6075a645ceb7b>",
    "pinboard": "[pinboard](<https://pinboard.opera.com/view/6f30ddbc-c4d2-4fd9-8c35-9cba43a0b003>) \n[pinboard CAD](<https://pinboard.opera.com/view/46e5f111-ed87-4aa8-a692-78372649410e>) [pinboard Mechanical](<https://pinboard.opera.com/view/cf0e583c-6e52-4318-9625-362a7b055ef7>)",
    "opmold": "<https://cad.onshape.com/documents/78804918af624e6f063d2ad3/w/3a8663d0264ec49de38227bb/e/cd95596c0063ca5fd6de4beb>",
    "optake": "https://www.optakeftc.com/ <https://linktr.ee/openflap_openmold>",
    "wr": "650NP WR: https://www.youtube.com/watch?v=KaQI9TnmK7E",
    "beltgen": "[2 pulley simple beltgen](<https://cad.onshape.com/documents/c163c756b5096bcd95e5692a/w/44c5f14084d55dd0388345f0/e/cf391d827826f30c60340bcc>) \n[Beltgen with idlers and calcs](<https://cad.onshape.com/documents/b273b67c06b86b78b01b6f3a>)",
    "ftcpartslib": "https://cad.onshape.com/appstore/apps/Design%20&%20Documentation/6515cfb91574253b1b96a6ba",
    "render": "[Blender for FTC](<https://ryanhcode.gitbook.io/blender4ftc/>) \n[TerraBlend render/animation tutorials](<https://youtube.com/playlist?list=PLN0ahmLmTINMHjCaRldqXcQ6850XqSyyD&si=ULvOSjRj4dcvaeGF>)",
    "breakbeam": "How to wire a 2 part break beam sensor (If one side has 3 wires and the other side has 2 wires): 1. Remove all of the connectors from the break beam sensors. 2. Connect the black wire from both parts together and crimp into 1 pin. (If no crimping equipment, solder or join this new single connection point to the black wire on a standard 4 pin sensor cable). 3. Connect the red wire from both parts together and crimp into 1 pin. (If no crimping equipment, solder or join this new single connection point to the red wire on a standard 4 pin sensor cable). 4. Crimp the signal cable to be the correct type (or alternatively solder onto the white cable of a standard sensor cable). 5. If crimping, make sure you insert the wires into the correct spots on the JST-PH 4pin housing.",
    "configlib": "[Config lib](<https://forms.gle/Q3uE1LWMjUByHPg58>) \n[How to use](<https://docs.google.com/document/d/1VPqlQXmah0Iye18LiESBxKin5IhrcJWbNSKKjIv0kAk/edit?tab=t.0>)",
    "cm": "https://ftc-resources.firstinspires.org/ftc/game/manual",
    "epa": "https://statcube.vercel.app/",
    "limits": "Possession Limit: 4 Scoring Elements (g407) Expansion Limits: 29\" Vertical, 24\" Horizontal (r105)",
    "ppdt": "https://www.youtube.com/watch?v=FgXQw3s5k9g",
    "beltcalc": "[ReCalc ](<https://www.reca.lc/belts>) https://petrustoica.github.io/beltcalc/",
    "hive": "Calibration Guide PDF (from event setup guide):\n https://cdn.discordapp.com/attachments/1527459271212798054/1549151131987476621/So_lets_say_you_want_to_calibrate_the_HIVE_-_V1.0.pdf?ex=6aa9a6eb&is=6aa8556b&hm=94f0a5f8b3fe261abb8e38483cd296cae45d09ddf2efb758076e933f8e33fdea& \nCalibration Requirements Table (from event setup guide):\n https://cdn.discordapp.com/attachments/1527459271212798054/1549150669582241812/image.png?ex=6aa9a67d&is=6aa854fd&hm=ef2f6f0a3463ae5c000a0bff13df415fc2f853ad282d62858fa5e12cab13c858&",
    "hackclub": "<https://hackclub.com/fiscal-sponsorship/first/>",
    "hcb": "<https://hackclub.com/fiscal-sponsorship/first/>",
    "grants": "<https://docs.google.com/spreadsheets/d/1r3xjIrP7uX1hlVNqKqBSDIXmQeQRP2pLLYg5KN7jqs4/edit?usp=drivesdk>",
    "xt30": "[Troubleshooting](<https://docs.revrobotics.com/duo-control/troubleshooting-the-control-system/expansion-hub-troubleshooting#xt30-pins-are-compressed>) <- Do this first, to fix/prevent voltage drops and disconnects \n[Retention Block](<https://www.printables.com/model/624466-xt-30-retention-block-for-controlexpansion-hub>) ⚠️ Warning: Adding a retention block or similar (e.g. using glue) *without* first spreading the pins as shown in the troubleshooting guide can lead to a connection that seems secure but is electrically faulty, causing voltage drops and disconnects!",
    "partslib": "https://cad.onshape.com/appstore/apps/Design%20&%20Documentation/6515cfb91574253b1b96a6ba",
    "octoquad": "# Octoquad - **[Website](https://www.tindie.com/products/digitalchickenlabs/octoquad-ftc-ed-mk2-8x-encoderpwm-imu/)** - **[Documentation](https://github.com/DigitalChickenLabs/OctoQuad/tree/master/documentation)**",
    "fs": "[FTCDesign Featurescripts](<https://cad.onshape.com/documents/97721efb7fbf764743af6da4/>) \n[General featurescripts](<https://github.com/dcowden/featurescript>) \n[Belt Gen](<https://cad.onshape.com/documents/c163c756b5096bcd95e5692a>) \n[Pulley Gen](<https://cad.onshape.com/documents/a116695750b054564ac11cbb/w/2025d9645023834db075348e/e/87987a3f29f6075a645ceb7b>) \n[Wheel Gen](<https://cad.onshape.com/documents/7ad7ca50c381036492cab695>) \n[Spool Gen](<https://cad.onshape.com/documents/761024cb69916ef24796adf4>) \n[Gear Gen](<https://cad.onshape.com/documents/f349bdd78c53f3325055aefc>) \n[Open Source Flop](<https://linktr.ee/openflap_openmold>) \n[Open Source Intake Tubing](<https://github.com/Hudson-1/opLibrary/tree/main/opTake>) \n[Open Source Misumi Slides](<https://cad.onshape.com/documents/f733a4dbb62b9d5ad77ce67c>) \n[Open Source Misumi Inserts](<https://github.com/Hudson-1/opLibrary/tree/main/opInsert>)",
    "op": "[OpTake](<https://github.com/Hudson-1/opLibrary/tree/main/opTake>) \n[FlopTake](<https://linktr.ee/openflap_openmold>) \n[OpInsert](<https://github.com/Hudson-1/opLibrary/tree/main/opInsert>) \n[OpSlides](<https://cad.onshape.com/documents/f733a4dbb62b9d5ad77ce67c/w/8547dd1f117f71f08076b593/e/b3eccd2e0ea51f72a618e9a8?configuration=List_sYN5isH1PpxJWD%3D_210%3BList_w67Z9Dfjpumv76%3D_5&renderMode=0&uiState=686aedd367892d702481263b>) \n[OpMold](<https://cad.onshape.com/documents/78804918af624e6f063d2ad3/w/3a8663d0264ec49de38227bb/e/cd95596c0063ca5fd6de4beb>) \n[OpSpool](<https://cad.onshape.com/documents/761024cb69916ef24796adf4/w/3b4e2ddf805c257161fc8178/e/b2c99289828f511762ed90ea>) \n[OpWheel](<https://cad.onshape.com/documents/7ad7ca50c381036492cab695/w/f446daf1a21bb344d96eb600/e/e12212ceda747ac117b3560f>)",
}
