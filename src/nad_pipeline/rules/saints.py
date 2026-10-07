"""Words that follow "ST" in a street name when ST means Saint.

Derived from NAD r24 (data/research/saint-vs-street.md, "Saint allow list"; counts per word in
data/research/st_work/saint_allow_list.csv). A word qualifies if it follows a leading ST in at
least two distinct state+name pairs, or appears spelled out as SAINT/SAINTE <word> anywhere in
NAD r24, or is in a US place name "St./Saint <word>", or is on TIGER-ROAR's saint list. Route
and type words, directionals, numbers and STATE, NO, CR, SUNSET, WEB, SING, FOUNTAIN, LAKES,
TIDE and DELIGHT are excluded. Apostrophes are removed (MARY'S -> marys).
"""

SAINT_WORDS = frozenset({
    "adalbert", "adalberts", "agatha", "agnes", "alban", "albans", "albert", "amand",
    "amant", "ambrose", "andre", "andrew", "andrews", "angela", "ann", "anna", "anne",
    "annes", "anns", "anthony", "anthonys", "antoine", "anton", "armands", "asaph", "aubin",
    "aubins", "augusta", "augustine", "augustines", "barbara", "barnabas", "bartholomew",
    "barts", "bedes", "benedict", "benet", "bernadette", "bernard", "bernards",
    "bonaventure", "boniface", "brendan", "brides", "bridget", "bridgets", "brigid",
    "bruno", "camillus", "canvinette", "casimir", "catharine", "catherine", "catherines",
    "cecelia", "cecilia", "charles", "christina", "christopher", "christophers", "clair",
    "claire", "clairs", "clairsville", "clare", "claude", "clement", "clere", "cloud",
    "crispin", "crispins", "croix", "cuthbert", "cyr", "cyril", "david", "davids", "denis",
    "dennis", "dolores", "dominic", "dorothy", "dunstans", "edith", "edmund", "edmunds",
    "edward", "edwards", "elias", "elizabeth", "elizabeths", "ellen", "elmo", "elmos",
    "emanuel", "emilion", "erics", "etienne", "eugene", "faustina", "felix", "ferdinand",
    "fillans", "florence", "florent", "florian", "frances", "francis", "francois",
    "gabriel", "gallen", "gaspar", "genevieve", "george", "georges", "germain", "germaine",
    "gertrude", "giles", "gregory", "gregorys", "hedwig", "helen", "helena", "helens",
    "henry", "herman", "hilaire", "honore", "hubbins", "huberts", "ignatius", "isidore",
    "ives", "jacob", "jacobs", "jacques", "james", "jean", "jerome", "joachim", "joan",
    "joe", "john", "johns", "johnsbury", "johnsville", "jones", "jordan", "joseph",
    "josephs", "jovite", "jude", "judes", "jules", "julian", "julien", "justin", "kateri",
    "katherine", "katherines", "kevin", "kilian", "kitts", "labre", "landry", "lauren",
    "laurence", "laurent", "lawrence", "lazare", "leger", "leo", "leon", "leonard",
    "leonards", "leos", "lewis", "libory", "linus", "lo", "louis", "louisville", "lucia",
    "lucie", "lucy", "luke", "lukes", "madeleine", "malo", "marc", "marcel", "marcella",
    "margaret", "margarets", "margarett", "marie", "mark", "marks", "martha", "martin",
    "martins", "mary", "marys", "mathews", "mathias", "matthew", "matthews", "maurice",
    "meena", "mellion", "michael", "michaels", "michel", "michelle", "mihiel", "monica",
    "moritz", "nicholas", "nick", "norbert", "olaf", "onge", "paris", "patrick", "patricks",
    "pats", "paul", "pauls", "peter", "peters", "petersburg", "philip", "philips",
    "phillip", "phillips", "philomena", "pierre", "pius", "raphael", "raymond", "regina",
    "regis", "remy", "rene", "renee", "richard", "richards", "rita", "ritas", "robert",
    "roberts", "rocco", "roch", "ronan", "rosalie", "rose", "sebald", "sebastian", "simon",
    "simons", "sophia", "stanislaus", "stephan", "stephen", "stephens", "stevens",
    "tammany", "teresa", "theresa", "therese", "thomas", "timothy", "tropez", "ursula",
    "veran", "victor", "vincent", "vincents", "vrain", "wendel", "william", "williams",
    "xavier",
})
