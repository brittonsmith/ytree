"""
TreeNode class and member functions



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2016, Britton Smith <brittonsmith@gmail.com>
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import numpy as np

from yt.extern.six import \
    string_types
from yt.frontends.ytdata.utilities import \
    save_as_dataset
from yt.funcs import \
    get_output_filename
from yt.utilities.exceptions import \
    YTFieldNotFound

class TreeNode(object):
    """
    Class for objects stored in Arbors.

    Each TreeNode represents a halo in a tree.  A TreeNode knows
    its halo ID, the level in the tree, and its global ID in the
    Arbor that holds it.  It also has a list of its ancestors.
    Fields can be queried for it, its progenitor list, and the
    tree beneath.
    """
    def __init__(self, uid, arbor=None):
        """
        Initialize a TreeNode with at least its halo catalog ID and
        its level in the tree.
        """
        self.uid = uid
        self.arbor = arbor
        self.ancestors = None

    def add_ancestor(self, ancestor):
        """
        Add another TreeNode to the list of ancestors.

        Parameters
        ----------
        ancestor : TreeNode
            The ancestor TreeNode.
        """
        if self.ancestors is None:
            self.ancestors = []
        self.ancestors.append(ancestor)

    def __getitem__(self, key):
        """
        Return field vlues for this TreeNode, progenitor list, or tree.

        Parameters
        ----------
        key : string or tuple
            If a single string, it can be either a field to be queried or
            one of "tree" or "prog".  If a field, then return the value of
            the field for this TreeNode.  If "tree" or "prog", then return
            the list of TreeNodes in the tree or progenitor list.

            If a tuple, this can be either (string, string) or (string, int),
            where the first argument must be either "tree" or "prog".
            If second argument is a string, then return the field values
            for either the tree or the progenitor list.  If second argument
            is an int, then return the nth TreeNode in the tree or progenitor
            list list.

        Examples
        --------
        >>> # virial mass for this halo
        >>> print (my_tree["mvir"].to("Msun/h"))

        >>> # all TreeNodes in the progenitor list
        >>> print (my_tree["prog"])
        >>> # all TreeNodes in the entire tree
        >>> print (my_tree["tree"])

        >>> # virial masses for the progenitor list
        >>> print (my_tree["prog", "mvir"].to("Msun/h"))

        >>> # the 3rd TreeNode in the progenitor list
        >>> print (my_tree["prog", 2])

        Returns
        -------
        float, ndarray/YTArray, TreeNode

        """
        arr_types = ("prog", "tree")
        if isinstance(key, tuple):
            if len(key) != 2:
                raise SyntaxError(
                    "Must be either 1 or 2 arguments.")
            if key[0] not in arr_types:
                raise SyntaxError(
                    "First argument must be one of %s." % str(arr_types))
            return getattr(self, "_%s" % key[0])(key[1])
        else:
            if isinstance(key, string_types):
                # return the progenitor list or tree nodes in a list
                if key in arr_types:
                    return getattr(self, "_%s_nodes" % key)
                # return field value for this node
                else:
                    if key not in self.arbor._field_data:
                        raise YTFieldNotFound(key, self.arbor)
                    return self.arbor._get_field(key)[self.uid]
            else:
                raise SyntaxError("Single argument must be a string.")

    def __repr__(self):
        return "TreeNode[%d]" % self.my_id

    _my_id = None
    @property
    def my_id(self):
        if self._my_id is None:
            if "uid" in self.arbor._field_data:
                self._my_id = self["uid"]
            else:
                self._my_id = self.uid
        return self._my_id

    _tfi = None
    @property
    def _tree_field_indices(self):
        """
        Return the field array indices for all TreeNodes in
        the tree beneath, starting with this TreeNode.
        """
        if self._tfi is None:
            self._set_tree_attrs()
        return self._tfi

    _tn = None
    @property
    def _tree_nodes(self):
        """
        Return a list of all TreeNodes in the tree beneath,
        starting with this TreeNode.
        """
        if self._tn is None:
            self._set_tree_attrs()
        return self._tn

    def _set_tree_attrs(self):
        """
        Prepare the TreeNode list and field indices.
        """
        tfi = []
        tn = []
        for my_node in self.twalk():
            tfi.append(my_node.uid)
            tn.append(my_node)
        self._tfi = np.array(tfi)
        self._tn = tn

    _lfi = None
    @property
    def _prog_field_indices(self):
        """
        Return the field array indices for all TreeNodes in
        the progenitor list, starting with this TreeNode.
        """
        if self._lfi is None:
            self._set_prog_attrs()
        return self._lfi

    _ln = None
    @property
    def _prog_nodes(self):
        """
        Return a list of all TreeNodes in the progenitor list, starting
        with this TreeNode.
        """
        if self._ln is None:
            self._set_prog_attrs()
        return self._ln

    def _set_prog_attrs(self):
        """
        Prepare the progenitor list list and field indices.
        """
        lfi = []
        ln = []
        for my_node in self.lwalk():
            lfi.append(my_node.uid)
            ln.append(my_node)
        self._lfi = np.array(lfi)
        self._ln = ln

    def twalk(self):
        r"""
        An iterator over all TreeNodes in the tree beneath,
        starting with this TreeNode.

        Examples
        --------

        >>> for my_node in my_tree.twalk():
        ...     print (my_node)

        """
        yield self
        if self.ancestors is None:
            return
        for ancestor in self.ancestors:
            for a_node in ancestor.twalk():
                yield a_node

    def lwalk(self):
        r"""
        An iterator over all TreeNodes in the progenitor list,
        starting with this TreeNode.

        Examples
        --------

        >>> for my_node in my_tree.lwalk():
        ...     print (my_node)

        """
        my_node = self
        while my_node is not None:
            yield my_node
            if my_node.ancestors is None:
                my_node = None
            else:
                my_node = my_node.arbor.selector(my_node.ancestors)

    def _tree(self, field):
        r"""
        Return a requested field for all TreeNodes in the tree
        beneath, starting with this TreeNode.

        Parameters
        ----------
        field : string
            The field to be queried.

        Examples
        --------
        >>> print (my_tree["tree", "mvir"].to("Msun/h"))

        Returns
        -------
        ndarray or YTArray

        """
        if isinstance(field, string_types):
            return self.arbor._field_data[field][self._tree_field_indices]
        else:
            return self._tree_nodes[field]

    def _prog(self, field):
        r"""
        Return a requested field for all TreeNodes in the progenitor list,
        starting with this TreeNode.  By default, the progenitor list traces
        the most massive progenitor in the tree.

        Parameters
        ----------
        field : string
            The field to be queried.

        Examples
        --------
        >>> print (my_tree["prog", "mvir"].to("Msun/h"))

        Returns
        -------
        ndarray or YTArray

        """
        if isinstance(field, string_types):
            return self.arbor._field_data[field][self._prog_field_indices]
        else:
            return self._prog_nodes[field]

    def save_tree(self, filename=None, fields=None):
        r"""
        Save the tree to a file.

        The saved tree can be re-loaded as an arbor.

        Parameters
        ----------
        filename : optional, string
            Output filename.  Include a trailing "/" to indicate
            a directory.
            Default: "arbor_<uid>.h5"
        fields : optional, list of strings
            The fields to be saved.  If not given, all
            fields will be saved.

        Returns
        -------
        filename : string
            The filename of the saved arbor.

        Examples
        --------

        >>> import ytree
        >>> a = ytree.load("rockstar_halos/trees/tree_0_0_0.dat")
        >>> # save the first tree
        >>> fn = a[0].save_tree()
        >>> # reload it
        >>> a2 = ytree.load(fn)

        """
        keyword = "tree_%d" % self.my_id
        filename = get_output_filename(filename, keyword, ".h5")
        if fields is None:
            fields = self.arbor._field_data.keys()
        ds = {}
        for attr in ["hubble_constant",
                     "omega_matter",
                     "omega_lambda"]:
            if hasattr(self.arbor, attr):
                ds[attr] = getattr(self.arbor, attr)
        extra_attrs = {"box_size": self.arbor.box_size,
                       "arbor_type": "ArborArbor",
                       "unit_registry_json":
                       self.arbor.unit_registry.to_json()}
        data = {}
        for field in fields:
            data[field] = self["tree", field]

        # If this node is not the root of the tree,
        # it has to become a root in order to reload it.
        data["tree_id"][:] = self["uid"]
        data["desc_id"][0] = -1

        save_as_dataset(ds, filename, data,
                        extra_attrs=extra_attrs)
        return filename
