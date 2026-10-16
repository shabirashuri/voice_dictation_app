"""Vocabulary boosted in speech-to-text (AssemblyAI `keyterms_prompt`).

Terms the recogniser tends to mishear. Keep at most 100 terms of 50 characters
or fewer (the service limits); they bias recognition, they are never inserted
into a report.
"""

PATHOLOGY_TERMS = [
    # organisms and gastric
    "Helicobacter pylori", "foveolar hyperplasia", "intestinal metaplasia", "chronic active gastritis",
    "lamina propria", "muscularis mucosae", "muscularis propria", "Barrett's esophagus", "gastric antrum",
    "oxyntic mucosa", "Ménétrier disease", "Sjögren syndrome",
    # growth patterns and cytology
    "dysplasia", "hyperplasia", "metaplasia", "atypia", "adenocarcinoma", "adenoma", "carcinoma in situ",
    "squamous cell carcinoma", "basal cell carcinoma", "invasive ductal carcinoma", "ductal carcinoma in situ",
    "lobular carcinoma", "melanoma", "lymphovascular invasion", "perineural invasion", "mitotic figures",
    "pleomorphism", "necrosis", "desmoplastic stroma", "granuloma", "fibrosis", "ulceration", "erosion",
    "neutrophils", "lymphocytes", "plasma cells", "eosinophils", "crypt abscess", "villous atrophy",
    # skin, breast, colon
    "epidermis", "dermis", "hyperkeratosis", "parakeratosis", "acanthosis", "spongiosis", "solar elastosis",
    "tubular adenoma", "tubulovillous adenoma", "hyperplastic polyp", "sessile serrated lesion",
    "fibroadenoma", "core biopsy", "punch biopsy", "shave biopsy", "excision biopsy",
    # reporting
    "hematoxylin and eosin", "immunohistochemistry", "formalin fixed", "paraffin embedded", "tan-white",
    "margins negative", "margins involved", "clinical correlation", "lymph nodes", "micrometres",
    "centimetres", "millimetres",
]
