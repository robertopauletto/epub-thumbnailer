#!/usr/bin/python

#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Author: Mariano Simone (http://marianosimone.com)
# Version: 1.0
# Name: epub-thumbnailer
# Description: An implementation of a cover thumbnailer for epub files
# Installation: see README

# Roberto Pauletto
# Some small changes to adapt as a module
# you can pass a string with format 000x000 as size
# if you dont'pass the output file will be inferred as the ebook name with
# "png" extension

import os
import re
import traceback
import zipfile
from io import BytesIO
from typing import Union, Tuple, Any, BinaryIO
from urllib.request import urlopen
from xml.dom import minidom

from PIL import Image

img_ext_regex = re.compile(r'^.*\.(jpg|jpeg|png)$', flags=re.IGNORECASE)
cover_regex = re.compile(r'.*cover.*\.(jpg|jpeg|png)', flags=re.IGNORECASE)
size_regex = re.compile(r'\d{1,4}[xX]\d{1,4}')


class EpubThumbnailerException(Exception):
    pass


def get_cover_from_manifest(epub: BinaryIO) -> Union[None, str]:
    """
    :param epub: ebook stream
    :return: the image path or None if not found
     """
    # open the main container
    container = epub.open("META-INF/container.xml")
    container_root = minidom.parseString(container.read())

    # locate the rootfile
    elem = container_root.getElementsByTagName("rootfile")[0]
    rootfile_path = elem.getAttribute("full-path")

    # open the rootfile
    rootfile = epub.open(rootfile_path)
    rootfile_root = minidom.parseString(rootfile.read())

    # find possible cover in meta
    cover_id = None
    for meta in rootfile_root.getElementsByTagName("meta"):
        if meta.getAttribute("name") == "cover":
            cover_id = meta.getAttribute("content")
            break

    # find the manifest element
    manifest = rootfile_root.getElementsByTagName("manifest")[0]
    for item in manifest.getElementsByTagName("item"):
        item_id = item.getAttribute("id")
        item_properties = item.getAttribute("properties")
        item_href = item.getAttribute("href")
        item_href_is_image = img_ext_regex.match(item_href.lower())
        item_id_might_be_cover = item_id == cover_id or (
                    'cover' in item_id and item_href_is_image)
        item_properties_might_be_cover = item_properties == cover_id or (
                    'cover' in item_properties and item_href_is_image)
        if item_id_might_be_cover or item_properties_might_be_cover:
            return os.path.join(os.path.dirname(rootfile_path), item_href)

    return None


def get_cover_by_filename(epub: BinaryIO) -> Union[str, None]:
    """
    Find a cover by filename according to the pattern
    `.*cover.*\\.(jpg|jpeg|png` first, otherwise will look for the best image
    within jpg, jpeg and png files

    :param epub: ebook stream
    :return:
    """
    no_matching_images = []
    for fileinfo in epub.filelist:
        if cover_regex.match(fileinfo.filename):
            return fileinfo.filename
        if img_ext_regex.match(fileinfo.filename):
            no_matching_images.append(fileinfo)
    return _choose_best_image(no_matching_images)


def _choose_best_image(images: list) -> Union[str, None]:
    """Return the mast large image in  'images` """
    if images:
        return max(images, key=lambda f: f.file_size)
    return None


def extract_cover(cover_path: str, epub: BinaryIO,
                  size: Tuple[float, float], output_file: str) -> bool:
    """
    Copy to `output_file` the cover image with  `size`
    :param cover_path:
    :param epub:
    :param size:
    :param output_file:
    :return:
    """
    if cover_path:
        cover = epub.open(cover_path)
        im = Image.open(BytesIO(cover.read()))
        im.thumbnail(size, Image.ANTIALIAS)
        if im.mode == "CMYK":
            im = im.convert("RGB")
        im.save(output_file, "PNG")
        return True
    return False


def _parse_size(size: Any) -> Tuple[float, float]:
    """Size parsing and normalization"""
    if not size:
        return 256, 256

    prompt = "Size must be a float (same height/width) or a string " \
             "representing height/width (eg. 256.34x300)"

    if isinstance(size, int) or isinstance(size, float):
        return size, size
    if isinstance(size, str):
        if not size_regex.match(size):
            raise ValueError(prompt)
        try:
            return tuple(float(val) for val in size.lower().split('x', 1))
        except:
            raise ValueError("Cannot parse floats from size parameter")
    else:
        raise ValueError(prompt)


def _parse_output(filename: str, ext: str = '.png') -> str:
    """
    change  `filename` extension to `ext`
    :param filename:
    :param ext:
    :return:
    """
    folder, fn = os.path.split(os.path.abspath(filename))
    fn, _ = os.path.splitext(fn)
    return os.path.join(folder, f"{fn}{ext}")


def _formal_checks(filein: str, fileimg: str, size: Union[str, int, float]):
    """
    Params formal check and normalization
    :param filein:
    :return:
    """
    filein = os.path.abspath(filein)
    fileimg = fileimg if fileimg is not None else _parse_output(filein)
    size = _parse_size(size)
    return filein, fileimg, size


def get_cover(filein, fileimg=None, size=None) -> Union[str, None]:
    """
    Main method, scans 'filein` for cover image, then create a
    `fileimg` thumbnail with `size`
    :param filein: the .epub file
    :param fileimg: if provided will be the thumbnail filename, otherwise the
                    thumbnail will be placed into the .epub folder with the
                    same name and extension .png
    :param size: should be a single integer or float (same width/heigth) or
                 a string with pattern 999x999
    :return: the thumbnail filename created, None if operation fails for any
             reason
    """
    # formal checks and normalization
    input_file, output_file, size = _formal_checks(filein, fileimg, size)

    # Don't care about online books, original feature removed
    if not os.path.exists(input_file):
        raise ValueError(f"{filein} does not exists or can't be accessed")

    with open(input_file, "rb") as fh:
        epub = zipfile.ZipFile(BytesIO(fh.read()), "r")

    extraction_strategies = [get_cover_from_manifest, get_cover_by_filename]

    for strategy in extraction_strategies:
        try:
            cover_path = strategy(epub)
            if extract_cover(cover_path, epub, size, output_file):
                return output_file
        except Exception as ex:
            prompt = f"Error getting cover using {stratey.__name__}:\n"\
                     f"{ex}"
            raise EpubThumbnailerException(prompt)


if __name__ == '__main__':
    ebook = r'/home/robby/Downloads/' \
            r'Essential SQLAlchemy Mapping Python to databases ' \
            r'by Jason Myers, Rick Copeland (z-lib.org).epub'
    get_cover(ebook, fileimg='./test1.png', size=500)
    # print(_parse_size('x1 2200'))
