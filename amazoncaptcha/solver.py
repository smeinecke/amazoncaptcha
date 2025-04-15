from typing import Any, Dict
from PIL import Image
from io import BytesIO
import requests
import json
import zlib
import os

from .utils import cut_the_white, merge_horizontally, find_letter_boxes
from .exceptions import ContentTypeError

MONOWEIGHT = 1
MAXIMUM_LETTER_LENGTH = 33
MINIMUM_LETTER_LENGTH = 14
SUPPORTED_CONTENT_TYPES = ["image/jpeg"]


class AmazonCaptcha(object):
    _image_link: str
    letters: Dict[str, Any]

    def __init__(self, img, image_link=None, devmode=False):
        """Initializes the AmazonCaptcha instance.

        Args:
            img (str or io.BytesIO): Path to an input image OR an instance
                of BytesIO representing this image.
            devmode (bool, optional): If set to True, instead of 'Not solved',
                unrecognised letters will be replaced with dashes.

        """
        self.img = Image.open(img, "r")
        self.devmode = devmode

        self.letters = dict()
        self.result = dict()

        package_directory_path = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
        self.training_data_folder = os.path.join(package_directory_path, "training_data")
        self.alphabet = [filename.split(".")[0] for filename in os.listdir(self.training_data_folder)]

    @property
    def image_link(self):
        """Image link property is being assigned only if the instance was
        created using `fromlink` class method.

        If you have created an AmazonCaptcha instance using the constructor,
        the property will be equal to None which triggers the warning.

        """
        return None

    def _monochrome(self):
        """Makes a captcha pure monochrome.

        Literally says: "for each pixel of an image turn codes 0, 1 to a 0,
        while everything in range from 2 to 255 should be replaced with 255".
        *All the numbers stay for color codes.
        """
        self.img = self.img.convert("L")
        self.img = Image.eval(self.img, lambda a: 0 if a <= MONOWEIGHT else 255)

    def _find_letters(self):
        """Extracts letters from an image using found letter boxes.

        Populates 'self.letters' with extracted letters being PIL.Image instances.
        """
        letter_boxes = find_letter_boxes(self.img, MAXIMUM_LETTER_LENGTH)
        letters = [self.img.crop((letter_box[0], 0, letter_box[1], self.img.height)) for letter_box in letter_boxes]

        if (len(letters) == 6 and letters[0].width < MINIMUM_LETTER_LENGTH) or (len(letters) != 6 and len(letters) != 7):
            letters = [Image.new("L", (200, 70)) for i in range(6)]

        if len(letters) == 7:
            letters[6] = merge_horizontally(letters[6], letters[0])
            del letters[0]

        letters = [cut_the_white(letter) for letter in letters]
        self.letters = {str(k): v for k, v in zip(range(1, 7), letters)}

    def _save_letters(self):
        """Transforms separated letters into pseudo binary.

        Populates 'self.letters' with pseudo binaries.
        """
        for place, letter in self.letters.items():
            letter_data = list(letter.getdata())
            letter_data_string = "".join(["1" if pix == 0 else "0" for pix in letter_data])

            pseudo_binary = str(zlib.compress(letter_data_string.encode("utf-8")))
            self.letters[place] = pseudo_binary

    def _translate(self):
        """Finds patterns to extracted pseudo binary strings from data folder.

        Literally says: "for each pseudo binary scan every stored letter
        pattern and find a match".

        Returns:
            str: a solution if there is one OR
                'Not solved' if devmode set to False OR
                a solution where unrecognised letters will be replaces with dashes

        """
        for place, pseudo_binary in self.letters.items():
            for letter in self.alphabet:
                with open(
                    os.path.join(self.training_data_folder, letter + ".json"),
                    "r",
                    encoding="utf-8",
                ) as js:
                    data = json.loads(js.read())

                if pseudo_binary in data:
                    self.result[place] = letter
                    break

            else:
                self.result[place] = "-"

                if not self.devmode:
                    return "Not solved"

        return "".join(self.result.values())

    def solve(self, keep_logs=False, logs_path="not-solved-captcha.log"):
        """Runs the sequence of solving a captcha.

        Args:
            keep_logs (bool): Not solved captchas will be logged if True.
                Defaults to False.
            logs_path (str): Path to the file where not solved captcha
                links will be stored. Defaults to "not-solved-captcha.log".

        Returns:
            str: Result of the sequence.

        """
        self._monochrome()
        self._find_letters()
        self._save_letters()

        solution = self._translate()

        if solution == "Not solved" and keep_logs:
            with open(logs_path, "a", encoding="utf-8") as f:
                f.write("\n")

        return solution

    @classmethod
    def fromlink(cls, image_link, devmode=False, timeout=120):
        """Requests the given link and stores the content of the response
        as `io.BytesIO` that is then used to create AmazonCaptcha instance.

        This also means avoiding any local savings.

        Args:
            link (str): Link to Amazon's captcha image.
            devmode (bool, optional): If set to True, instead of 'Not solved',
                unrecognised letters will be replaced with dashes.
            timeout (int, optional): Requests timeout.

        Returns:
            AmazonCaptcha: Instance created based on the image link.

        Raises:
            ContentTypeError: If response headers contain unsupported
                content type.

        """
        response = requests.get(image_link, timeout=timeout)

        if response.headers["Content-Type"] not in SUPPORTED_CONTENT_TYPES:
            raise ContentTypeError(response.headers["Content-Type"])

        image_bytes_array = BytesIO(response.content)

        return cls(image_bytes_array, devmode)
